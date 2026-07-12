// Nav profile switcher: switching sets the cve_profile cookie server-side
// then reloads so every route resolves the newly-active profile. "+ New
// profile…" prompts for a name, creates it, and switches to it.
(function () {
  var sel = document.getElementById('profile-select');
  if (!sel) return;
  var current = sel.value;

  function toast(msg) {
    var t = document.getElementById('toast');
    if (!t) return;
    t.textContent = msg;
    t.hidden = false;
    setTimeout(function () { t.hidden = true; }, 2500);
  }

  sel.addEventListener('change', function () {
    if (sel.value === '__new__') {
      var name = (window.prompt('New profile name:') || '').trim();
      sel.value = current; // reset the select regardless
      if (!name) return;
      fetch('/api/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name })
      }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok) { toast(res.d.error || 'Could not create profile'); return; }
          window.location.reload();
        }).catch(function () { toast('Could not create profile'); });
      return;
    }
    var slug = sel.value;
    fetch('/api/profile/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slug: slug })
    }).then(function (r) {
      if (!r.ok) { toast('Could not switch profile'); sel.value = current; return; }
      window.location.reload();
    }).catch(function () { toast('Could not switch profile'); sel.value = current; });
  });
})();
