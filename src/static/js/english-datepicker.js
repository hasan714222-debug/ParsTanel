/* ========================================================================= */
/* File: english-datepicker.js                                               */
/* Role: Auto-converts datepicker inputs to native dark Gregorian inputs      */
/* ========================================================================= */

document.addEventListener("DOMContentLoaded", function() {
    const isEN = document.documentElement.lang === 'en' || !window.location.pathname.includes('-fa');
    if (!isEN) return;

    function initEnglishDateInputs() {
        const dateInputs = document.querySelectorAll("#bulkStartDate, #bulkEndDate, input[data-datepicker='gregorian']");
        dateInputs.forEach(input => {
            if (input) {
                input.type = "date";
                input.style.cursor = "pointer";
                input.style.direction = "ltr";
                input.style.textAlign = "left";
                input.style.colorScheme = "dark";
                input.removeAttribute("readonly");
            }
        });
    }

    initEnglishDateInputs();
    setTimeout(initEnglishDateInputs, 400);
});