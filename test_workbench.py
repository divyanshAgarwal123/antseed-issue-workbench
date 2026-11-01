"""Offline checks for pricing, selection and recovery; no model requests are sent."""
import json
import threading
import unittest
import urllib.request
from unittest.mock import patch

import workbench as app
import smoke_features as probe


def peer(name='a', price=0, score=70, image=False, staking=False):
    return {'peerId': name * 40, 'inputUsdPerMillion': price, 'outputUsdPerMillion': price,
            'protocol': 'openai-chat-completions',
            'reputationScore': score, 'capabilities': {'inputs': ['text', 'image'] if image else ['text']},
            'freeTier': {'base': {'stakersOnly': staking}}}


def model(name, peers):
    return {'id': name, 'type': 'text', 'peers': peers}


CATALOG = {'data': [model('gpt-oss-120b', [peer('a'), peer('b', price=2)]),
                    model('mistral-small-3-2-24b-instruct', [peer('c')]), model('fresh-model', [peer('d', image=True)])]}
FINDINGS = {'summary': 'Export reports success but omits the rectangle.', 'observed': ['The user reports an omission.'],
            'next_checks': ['Compare the exported image.'], 'uncertainty': 'The cause has not been checked.'}


def response(route, text):
    return {'choices': [{'message': {'content': text}}]}, {'status': 200, 'peer': route.split('@')[0], 'seconds': 1, 'usage': {'total_tokens': 20}}


class WorkbenchTests(unittest.TestCase):
    def test_free_selection_excludes_paid_low_score_and_staking(self):
        catalog = {'data': [model('mixed', [peer('a'), peer('b', price=1), peer('c', score=40), peer('d', staking=True)])]}
        self.assertEqual([offer['peer'] for offer in app.eligible_offers(catalog)], ['a' * 40])

    def test_new_model_names_and_image_requirement(self):
        state = {'offers': app.eligible_offers(CATALOG)}
        self.assertEqual(app.offer_pool(state, 'analyst', image=True)[0]['model'], 'fresh-model')
        with self.assertRaises(app.AntseedError):
            app.offer_pool(state, 'analyst', image=True, selected='a' * 40 + '@gpt-oss-120b')

    def test_stale_manual_choice_does_not_silently_switch(self):
        state = {'offers': app.eligible_offers(CATALOG)}
        with self.assertRaises(app.AntseedError) as caught:
            app.offer_pool(state, 'analyst', selected='gone@model')
        self.assertEqual(caught.exception.code, 'offer_unavailable')

    def test_specialist_search_service_is_not_a_chat_choice(self):
        search = peer('a'); search['categories'] = ['3d', 'search', 'data']
        self.assertEqual(app.eligible_offers({'data': [model('asset-search', [search])]}), [])

    def test_service_id_preserves_preference_when_catalog_alias_changes(self):
        mistral = peer('a'); mistral['serviceId'] = 'mistral-small-3-2-24b-instruct'
        state = {'offers': app.eligible_offers({'data': [model('mistral-small-3.2-24b-instruct', [mistral]), model('deepseek-v4-flash', [peer('b')])]})}
        self.assertEqual(app.offer_pool(state, 'reviewer')[0]['model'], 'mistral-small-3.2-24b-instruct')

    def test_retry_review_sends_no_analyst_request(self):
        state = {'offers': app.eligible_offers(CATALOG)}
        with patch.object(app, 'antseed_request', side_effect=lambda path, payload: response(payload['model'], 'Check the export first.')) as request:
            app.review('An export omits a shape.', FINDINGS, state, 'gpt-oss-120b', None, False, [], lambda event: None)
        self.assertEqual(request.call_count, 1)
        self.assertNotIn('response_format', request.call_args.args[1])

    def test_api_probe_pins_free_service_under_a_new_alias(self):
        free = peer('a'); free['serviceId'] = 'gpt-oss-120b'
        paid = peer('b', price=1)
        models = {'openai/gpt-oss-120b': model('openai/gpt-oss-120b', [paid, free])}
        self.assertEqual(probe.free_peer(models, ('gpt-oss-120b',)), ('openai/gpt-oss-120b', 'a' * 40))

    def test_budget_hold_keeps_values_and_stops_retry(self):
        failure = app.upstream_error(402, {'error': {'code': 'spend_limit_reached', 'limit': {'limit_usd': '0.01', 'spent_usd': '0', 'held_usd': '0.3'}}})
        pool = app.eligible_offers(CATALOG)[:2]
        with patch.object(app, 'antseed_request', side_effect=failure) as request:
            with self.assertRaises(app.AntseedError):
                app.run_step(pool, 'test', 'analyst', [], lambda event: None)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(failure.public()['details']['spent_usd'], '0')

    def test_empty_response_tries_only_next_free_pinned_offer(self):
        pool = app.eligible_offers(CATALOG)[:2]
        with patch.object(app, 'antseed_request', side_effect=[response(pool[0]['id'], ''), response(pool[1]['id'], 'Review ready.')]) as request:
            text, _, offer = app.run_step(pool, 'test', 'reviewer', [], lambda event: None)
        self.assertEqual(text, 'Review ready.')
        self.assertEqual(offer, pool[1])
        self.assertEqual([call.args[1]['model'] for call in request.call_args_list], [offer['id'] for offer in pool])

    def test_review_failure_preserves_analysis(self):
        def upstream(path, payload=None):
            if path == '/v1/models': return CATALOG, {}
            if 'gpt-oss-120b' in payload['model']: return response(payload['model'], json.dumps(FINDINGS))
            raise app.AntseedError('timeout', 'Provider timed out.')
        with patch.object(app, 'antseed_request', side_effect=upstream):
            result = app.analyze('A synthetic export issue happened.', None)
        self.assertEqual(result['findings'], FINDINGS)
        self.assertEqual(result['review_error']['code'], 'timeout')
        self.assertIsNone(result['reviewer'])

    def test_streamed_http_run_contains_partial_analysis_and_completion(self):
        def upstream(path, payload=None):
            if path == '/v1/models': return CATALOG, {}
            text = json.dumps(FINDINGS) if payload.get('response_format') else 'Confirm the exported image first.'
            return response(payload['model'], text)
        with patch.object(app, 'antseed_request', side_effect=upstream):
            server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/analyze', data=json.dumps({'issue': 'An export omits a rectangle.', 'stream': True}).encode(), headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(request) as result:
                    events = [json.loads(line) for line in result]
                self.assertIn('analysis', [event['event'] for event in events])
                self.assertEqual(events[-1]['event'], 'complete')
                self.assertNotEqual(events[-1]['result']['analyst_model'], events[-1]['result']['reviewer_model'])
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_recorded_example_makes_no_upstream_call(self):
        with patch.object(app, 'antseed_request') as upstream:
            server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/recorded') as result:
                    self.assertEqual(json.load(result)['result']['mode'], 'recorded')
                upstream.assert_not_called()
            finally:
                server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
