(function () {
    const form = document.getElementById('itemAddForm');
    if (!form) return;
    const card = document.getElementById('itemAddCard');
    const errorEl = document.getElementById('itemFormError');
    const okEl = document.getElementById('itemFormOk');
    const submitBtn = form.querySelector('button[type="submit"]');

    function show(el, message) {
        el.textContent = message;
        el.hidden = false;
    }

    // Collapse only when this file is running: with JS blocked the card stays
    // visible rather than becoming unreachable.
    if (card.hasAttribute('data-collapsible')) card.hidden = true;

    // Delegated so the toggle can sit anywhere on the page, before or after us.
    document.addEventListener('click', function (e) {
        const toggle = e.target.closest('[data-toggle-items]');
        if (!toggle) return;
        card.hidden = !card.hidden;
        toggle.textContent = card.hidden ? toggle.dataset.showLabel : toggle.dataset.hideLabel;
        toggle.setAttribute('aria-expanded', String(!card.hidden));
        if (!card.hidden) form.querySelector('input[name="name"]').focus();
    });

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        errorEl.hidden = true;
        okEl.hidden = true;
        submitBtn.disabled = true;

        fetch(form.action, {
            method: 'POST',
            body: new FormData(form),
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
        .then(function (resp) {
            return resp.json().catch(function () {
                throw new Error('Unexpected response from the server — try reloading the page.');
            }).then(function (data) {
                if (!resp.ok || !data.success) {
                    throw new Error(data.error || 'Something went wrong.');
                }
                return data.item;
            });
        })
        .then(function (item) {
            form.reset();
            show(okEl, 'Added “' + item.name + '”.');
            document.dispatchEvent(new CustomEvent('item:added', { detail: item }));
        })
        .catch(function (err) {
            show(errorEl, err.message || 'Network error. Please try again.');
        })
        .finally(function () {
            submitBtn.disabled = false;
        });
    });
})();
