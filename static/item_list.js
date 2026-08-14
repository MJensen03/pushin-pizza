// Menu page: each item is a full editable card, so let the server render the
// new one rather than rebuilding that markup here.
document.addEventListener('item:added', function () {
    window.location.reload();
});
