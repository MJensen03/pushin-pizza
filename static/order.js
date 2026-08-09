const inputs = document.querySelectorAll('.qty input');
const total = document.getElementById('total');
function updateTotal() {
    let cents = 0;
    inputs.forEach(i => cents += (parseInt(i.value) || 0) * parseInt(i.dataset.price));
    total.textContent = '$' + (cents / 100).toFixed(2);
}
inputs.forEach(i => i.addEventListener('input', updateTotal));
