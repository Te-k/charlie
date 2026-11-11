// Small behaviours, kept out of the templates so the Content-Security-Policy
// can forbid inline scripts. Loaded (without defer) in <head>: the listeners are
// attached to `document` before any image starts loading.

// <button data-busy>: show a spinner once clicked (slow network calls).
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-busy]");
  if (button) button.setAttribute("aria-busy", "true");
});

// <img data-fallback="remove|remove-parent|message">: handle broken remote images.
// Image errors don't bubble, so listen in the capture phase.
document.addEventListener(
  "error",
  (event) => {
    const img = event.target;
    if (!(img instanceof HTMLImageElement) || !img.dataset.fallback) return;
    if (img.dataset.fallback === "remove-parent") {
      img.parentElement.remove();
    } else if (img.dataset.fallback === "message") {
      const p = document.createElement("p");
      p.className = "rounded-lg bg-red-500/10 p-4 text-sm text-red-700 dark:text-red-300";
      p.textContent = "The photo could not be loaded.";
      img.replaceWith(p);
    } else {
      img.remove();
    }
  },
  true,
);

// <input data-filter>: hide list items ([data-name]) that don't match.
document.addEventListener("input", (event) => {
  if (!event.target.matches("[data-filter]")) return;
  const query = event.target.value.trim().toLowerCase();
  document.querySelectorAll("[data-name]").forEach((item) => {
    item.hidden = !item.dataset.name.includes(query);
  });
});
