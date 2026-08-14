// Pickups page: item_add.js fires `item:added` after a new menu item is saved.
// Splice it into every menu picker on the page so it is usable here without a
// round trip through the Menu page.
document.addEventListener('item:added', function (e) {
    const item = e.detail;
    document.querySelectorAll('[data-menu-picker]').forEach(function (picker) {
        const emptyNote = picker.querySelector('[data-empty-note]');
        if (emptyNote) emptyNote.remove();

        const box = document.createElement('input');
        box.type = 'checkbox';
        box.name = 'item_ids';
        box.value = item.id;
        // Pre-check it on the "create a pickup day" form only; existing events
        // keep the menu they were saved with.
        box.checked = picker.hasAttribute('data-check-new');

        const label = document.createElement('label');
        label.className = 'check';
        label.append(box, ' ' + item.name + ' (' + item.price + ')');
        picker.appendChild(label);
    });
});
