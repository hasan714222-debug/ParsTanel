
/* --- English Gregorian DatePicker JS (Step 77) --- */
document.addEventListener("DOMContentLoaded", function() {
    const isEN = document.documentElement.lang === 'en' || !window.location.pathname.includes('-fa');
    if (!isEN) return;

    const startInput = document.getElementById("bulkStartDate");
    const endInput = document.getElementById("bulkEndDate");

    [startInput, endInput].forEach(input => {
        if (input) {
            input.type = "date";
            input.style.cursor = "pointer";
            input.style.direction = "ltr";
            input.style.textAlign = "left";
            input.style.colorScheme = "dark";
        }
    });
});
