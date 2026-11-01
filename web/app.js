const $ = (id) => document.getElementById(id);

async function checkStatus() {
  try {
    const response = await fetch('/api/status');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Antseed is unavailable');
    const ready = data.analyst_model && data.reviewer_model;
    $('availability').innerHTML = `<span class="dot"></span><span>${ready ? 'Ready' : 'Free models unavailable'} · ${data.free_text_count} eligible free text models in a ${data.catalog_count}-model catalog</span>`;
    $('analyze').disabled = !ready;
  } catch (error) {
    $('availability').textContent = `Antseed connection failed: ${error.message}`;
    $('availability').classList.add('error');
    $('analyze').disabled = true;
  }
}

function fileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('Could not read the image'));
    reader.readAsDataURL(file);
  });
}

function formatMeta(meta) {
  const peer = meta.peer ? ` · provider ${meta.peer.slice(0, 10)}…` : '';
  const tokens = meta.usage?.total_tokens ? ` · ${meta.usage.total_tokens} tokens` : '';
  return `${meta.seconds}s${tokens}${peer}`;
}

$('example').addEventListener('click', () => {
  $('issue').value = 'When a coding agent sends a standard request field called prompt_cache_key, one provider returns HTTP 422. The same model is available from another provider that accepts the request. The buyer returns the first error instead of trying that provider.';
});

$('analyze').addEventListener('click', async () => {
  $('message').textContent = '';
  $('results').hidden = true;
  const issue = $('issue').value.trim();
  const file = $('image').files[0];
  if (issue.length < 12) {
    $('message').textContent = 'Add a fuller issue description first.';
    return;
  }
  if (file && file.size > 1_000_000) {
    $('message').textContent = 'Choose an image under 1 MB.';
    return;
  }
  $('analyze').disabled = true;
  $('message').textContent = 'Asking two free models through Antseed…';
  try {
    const image = file ? await fileAsDataUrl(file) : null;
    const response = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ issue, image }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    $('findings').textContent = JSON.stringify(data.findings, null, 2);
    $('review').textContent = data.review;
    $('analyst-meta').textContent = `${data.analyst_model}${formatMeta(data.analyst)}`;
    $('reviewer-meta').textContent = `${data.reviewer_model}${formatMeta(data.reviewer)}`;
    $('results').hidden = false;
    $('message').textContent = 'Analysis complete.';
  } catch (error) {
    $('message').textContent = `Could not complete the analysis: ${error.message}`;
  } finally {
    $('analyze').disabled = false;
  }
});

checkStatus();
