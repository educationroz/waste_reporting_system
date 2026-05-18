/* waste_system/static/web_app/js/main.js
   Shared utilities available on all pages via base.html.
   API helpers + showToast are defined inline in base.html
   since they need the JWT token from localStorage.
   This file is for page-agnostic utilities only.
*/

// Auto-set datetime-local min to now
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('input[type="datetime-local"]').forEach(el => {
        const now = new Date();
        now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
        el.min = now.toISOString().slice(0, 16);
    });
});