const $ = (id) => document.getElementById(id);
let catalog = null;
let imageData = null;
let imageName = '';
let run = null;
let runInput = null;
let busy = false;
let clock = null;

function offerById(id) { return catalog?.offers.find((offer) => offer.id === id); }
function orderedOffers(role) {
  const key = role === 'analyst' && imageData ? 'vision_analyst' : role;
  return (catalog?.orders[key] || []).map(offerById).filter(Boolean);
}
function chosenAnalyst() {
  return offerById($('analyst-choice').value) || orderedOffers('analyst')[0];
}
function reviewerOffers() {
  return orderedOffers('reviewer').filter((offer) => offer.model !== chosenAnalyst()?.model);
}
function chosenReviewer() {
  return reviewerOffers().find((offer) => offer.id === $('reviewer-choice').value) || reviewerOffers()[0];
}
function fillSelect(id, offers) {
  const select = $(id);
  const previous = select.value;
  select.replaceChildren(new Option('Automatic free selection', ''));
  offers.forEach((offer) => select.add(new Option(`${offer.model} · ${offer.provider} · $0`, offer.id)));
  if (offers.some((offer) => offer.id === previous)) select.value = previous;
  select.disabled = busy || !offers.length;
}
function describeOffer(offer) {
  if (!offer) return 'No eligible offer available. Refresh the catalog or view the recorded run.';
  return `${offer.model} · peer ${offer.peer.slice(0, 10)}… · score ${offer.reputation} · $0 input / output${offer.accepts_image ? ' · accepts images' : ''}`;
}
function updateRouting() {
  fillSelect('analyst-choice', orderedOffers('analyst'));
  fillSelect('reviewer-choice', reviewerOffers());
  $('analyst-offer').textContent = describeOffer(chosenAnalyst());
  $('reviewer-offer').textContent = describeOffer(chosenReviewer());
  $('analyze').disabled = busy || !chosenAnalyst() || !chosenReviewer();
}
async function checkStatus() {
  $('availability').textContent = 'Refreshing the live catalog…';
  $('refresh').disabled = true;
  try {
    const response = await fetch('/api/status');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || 'Antseed is unavailable.');
    catalog = data;
    $('availability').textContent = `${data.free_model_count} eligible free models / ${data.catalog_count} total · checked ${new Date(data.checked_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}`;
  } catch (error) {
    catalog = null;
    $('availability').textContent = `${error.message} Start your buyer or gateway, then refresh. The recorded run works offline.`;
  } finally {
    $('refresh').disabled = busy;
    updateRouting();
  }
}
function fileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('Could not read the image.'));
    reader.readAsDataURL(file);
  });
}
function setImage(data, name = '') {
  if (!busy) { $('results').hidden = true; $('progress').hidden = true; }
  imageData = data;
  imageName = name;
  $('image-preview').hidden = !data;
  if (data) $('preview').src = data;
  else $('preview').removeAttribute('src');
  $('image-name').textContent = name;
  updateRouting();
}
function showError(error) {
  $('error').hidden = false;
  $('error-title').textContent = error.message || 'The request could not be completed.';
  $('error-action').textContent = error.action || 'Refresh the offers and try again.';
  $('error-raw').textContent = JSON.stringify(error, null, 2);
  const limits = $('error-limits');
  limits.replaceChildren();
  limits.hidden = error.code !== 'spend_limit_reached';
  if (!limits.hidden) {
    [['Limit', 'limit_usd'], ['Spent', 'spent_usd'], ['Remaining', 'remaining_usd'], ['Temporary hold', 'held_usd']].forEach(([label, key]) => {
      const group = document.createElement('div');
      const term = document.createElement('dt');
      const value = document.createElement('dd');
      term.textContent = label;
      value.textContent = `$${Number(error.details?.[key] || 0).toFixed(2)}`;
      group.append(term, value);
      limits.append(group);
    });
  }
}
function fillList(id, values) {
  $(id).replaceChildren(...values.map((text) => {
    const item = document.createElement('li'); item.textContent = text; return item;
  }));
}
function metadata(model, meta) {
  if (!meta) return '';
  return `${model} · ${meta.seconds}s${meta.usage?.total_tokens ? ` · ${meta.usage.total_tokens} tokens` : ''} · peer ${meta.peer || 'not identified'}`;
}
function renderRun(pending = false) {
  if (!run) return;
  $('results').hidden = false;
  $('run-mode').textContent = run.mode === 'recorded' ? 'Recorded example · 2 November 2026' : pending ? 'Live run · review in progress' : run.review_error ? 'Live run · analysis saved, review incomplete' : 'Live run · complete';
  $('recorded-note').hidden = run.mode !== 'recorded';
  $('summary').textContent = run.findings.summary;
  fillList('observed', run.findings.observed);
  fillList('next-checks', run.findings.next_checks);
  $('uncertainty').textContent = run.findings.uncertainty;
  $('review').textContent = (run.review || (pending ? 'The second model is reviewing the draft…' : '')).replace(/\*\*/g, '');
  $('analyst-meta').textContent = metadata(run.analyst_model, run.analyst);
  $('reviewer-meta').textContent = metadata(run.reviewer_model, run.reviewer);
  $('review-warning').hidden = !run.review_error;
  $('review-error').textContent = run.review_error ? `${run.review_error.message} ${run.review_error.action}` : '';
  $('raw-result').textContent = JSON.stringify({...run, input: runInput}, null, 2);
  $('download').disabled = pending;
}
function stage(event) {
  const stages = ['discovery', 'analyst', 'reviewer'];
  document.querySelectorAll('[data-stage]').forEach((element) => {
    const index = stages.indexOf(element.dataset.stage);
    element.classList.toggle('active', element.dataset.stage === event.stage);
    element.classList.toggle('done', index < stages.indexOf(event.stage));
  });
  $('message').textContent = event.offer ? `${event.stage === 'analyst' ? 'Analyzing' : 'Reviewing'} with ${event.offer.model} · peer ${event.offer.peer.slice(0,10)}…${event.attempt > 1 ? ' · trying an alternate free offer' : ''}` : 'Checking currently eligible free offers…';
}
function setBusy(value) {
  busy = value;
  ['example', 'sample-image', 'recorded', 'refresh', 'image', 'remove-image', 'retry-review'].forEach((id) => $(id).disabled = value);
  $('issue').readOnly = value;
  updateRouting();
}
async function requestRun(path, payload, reviewOnly = false) {
  $('error').hidden = true;
  $('progress').hidden = false;
  setBusy(true);
  const start = Date.now();
  $('elapsed').textContent = '0s';
  clock = setInterval(() => $('elapsed').textContent = `${Math.floor((Date.now()-start)/1000)}s`, 1000);
  let complete = false;
  try {
    const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({...payload, stream:true})});
    if (!response.ok) {
      const data = await response.json(); throw Object.assign(new Error(), {publicError:data.error});
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    function consume(line) {
      if (!line.trim()) return;
      const event = JSON.parse(line);
      if (event.event === 'status') stage(event);
      if (event.event === 'analysis') { run = event.result; renderRun(true); }
      if (event.event === 'error') throw Object.assign(new Error(), {publicError:event.error});
      if (event.event === 'complete') {
        run = reviewOnly ? {...run, ...event.result, attempts:[...(run.attempts || []), ...(event.result.attempts || [])]} : event.result;
        complete = true; renderRun();
        if (run.review_error) showError(run.review_error);
        $('message').textContent = run.review_error ? 'Analysis is ready. The review could not finish; retry it without repeating the analysis.' : 'Both steps completed. Check the draft before acting on it.';
        document.querySelectorAll('[data-stage]').forEach((element) => { element.classList.remove('active'); element.classList.toggle('done', !(run.review_error && element.dataset.stage === 'reviewer')); });
      }
    }
    while (true) {
      const {value, done} = await reader.read();
      buffer += decoder.decode(value, {stream:!done});
      let newline;
      while ((newline = buffer.indexOf('\n')) >= 0) { const line = buffer.slice(0,newline); buffer = buffer.slice(newline+1); consume(line); }
      if (done) break;
    }
    consume(buffer);
    if (!complete) throw new Error('The connection ended before the run completed.');
  } catch (error) {
    const detail = error.publicError || {message:error.message || 'The request failed.', action:'Refresh offers and try again.'};
    if (reviewOnly && run) { run.review_error = detail; renderRun(); }
    showError(detail);
    $('message').textContent = 'Request stopped. Read the recovery steps below.';
  } finally {
    clearInterval(clock); setBusy(false);
  }
}
$('issue').addEventListener('input', () => {
  $('characters').textContent = `${$('issue').value.length} / 5000`;
  if (!busy) { $('results').hidden = true; $('progress').hidden = true; }
});
$('example').addEventListener('click', () => {
  $('issue').value = 'Synthetic test: the export button reports success, but the downloaded file is missing a blue rectangle shown in the preview. Record the failure and suggest the next checks.';
  $('issue').dispatchEvent(new Event('input'));
  $('results').hidden = true; $('error').hidden = true; $('progress').hidden = true;
  $('image').value = ''; setImage(null);
});
$('sample-image').addEventListener('click', async () => {
  try {
    const response = await fetch('/sample.png');
    if (!response.ok) throw new Error('The sample screenshot is unavailable.');
    setImage(await fileAsDataUrl(await response.blob()), 'vision-test.png');
    $('image').value = '';
    $('issue').value = 'Synthetic screenshot test: record the color and shape in the attached image. Suggest one check after exporting the preview.';
    $('issue').dispatchEvent(new Event('input'));
  } catch (error) { showError({message:error.message}); }
});
$('image').addEventListener('change', async () => {
  const file = $('image').files[0];
  if (!file) return setImage(null);
  if (file.size > 1_000_000 || !['image/png','image/jpeg','image/webp'].includes(file.type)) {
    $('image').value = ''; setImage(null); return showError({message:'Choose a PNG, JPEG or WebP image under 1 MB.'});
  }
  try { setImage(await fileAsDataUrl(file), file.name); } catch (error) { showError({message:error.message}); }
});
$('remove-image').addEventListener('click', () => { $('image').value = ''; setImage(null); });
$('analyst-choice').addEventListener('change', updateRouting);
$('reviewer-choice').addEventListener('change', updateRouting);
$('refresh').addEventListener('click', checkStatus);
$('analyze').addEventListener('click', () => {
  const issue = $('issue').value.trim();
  if (issue.length < 12) return showError({message:'Describe the issue in at least 12 characters.'});
  run = null; runInput = {issue, has_image:!!imageData, image_name:imageName || null};
  $('results').hidden = true;
  requestRun('/api/analyze', {issue, image:imageData, analyst_choice:$('analyst-choice').value || null, reviewer_choice:$('reviewer-choice').value || null});
});
$('retry-review').addEventListener('click', () => requestRun('/api/review', {issue:runInput.issue, findings:run.findings, analyst_model:run.analyst_model, has_image:runInput.has_image, reviewer_choice:$('reviewer-choice').value || null}, true));
$('recorded').addEventListener('click', async () => {
  try {
    const response = await fetch('/api/recorded');
    if (!response.ok) throw new Error('The recorded run could not be loaded.');
    const data = await response.json();
    run = data.result; runInput = {issue:data.issue, has_image:false};
    $('issue').value = data.issue; $('issue').dispatchEvent(new Event('input'));
    $('image').value = ''; setImage(null);
    $('error').hidden = true; $('progress').hidden = true; renderRun();
  } catch (error) { showError({message:error.message}); }
});
$('download').addEventListener('click', () => {
  if (!run) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify({...run, input:runInput},null,2)], {type:'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = `antseed-${run.mode || 'live'}-run.json`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
checkStatus();
