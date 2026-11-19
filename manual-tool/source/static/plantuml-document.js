(() => {
  const endpoint = "http://127.0.0.1:8765/api/plantuml/render";
  const diagrams = [...document.querySelectorAll("[data-plantuml-diagram]")];
  const save = document.querySelector("[data-plantuml-save]");
  const states = diagrams.map((diagram) => {
    const source = diagram.querySelector("textarea");
    const image = diagram.querySelector("img");
    const status = diagram.querySelector("output");
    const state = { source, rendered: image.hasAttribute("src") ? source.value : null, generation: 0 };
    let timer;
    let active;

    function schedule() {
      const value = source.value;
      const generation = ++state.generation;
      clearTimeout(timer);
      active?.abort();
      updateSave();
      if (value === state.rendered) {
        status.textContent = "";
        return;
      }
      status.textContent = "図を更新中…";
      timer = setTimeout(async () => {
        active = new AbortController();
        try {
          const response = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/vnd.manual-tool.plantuml" },
            body: value,
            signal: active.signal
          });
          const payload = await response.json();
          if (generation !== state.generation) return;
          if (!response.ok) {
            status.textContent = payload.detail;
            return;
          }
          image.src = payload.svg;
          image.hidden = false;
          state.rendered = value;
          status.textContent = "";
          updateSave();
        } catch {
          if (generation === state.generation) {
            status.textContent = "図を更新できません。ManualToolを起動して「再試行」を押してください。";
          }
        }
      }, 400);
    }

    source.addEventListener("input", schedule);
    diagram.querySelector("button").addEventListener("click", schedule);
    return state;
  });

  function updateSave() {
    save.disabled = states.some(({ source, rendered }) => source.value !== rendered);
  }

  save.addEventListener("click", () => {
    updateSave();
    if (save.disabled) return;
    const copy = document.documentElement.cloneNode(true);
    copy.querySelectorAll("[data-plantuml-diagram]").forEach((diagram, index) => {
      const textarea = diagram.querySelector("textarea");
      textarea.textContent = "\n" + states[index].source.value;
      diagram.querySelector("details").open = false;
      diagram.querySelector("output").textContent = "";
    });
    const html = new Blob(["<!doctype html>\n", copy.outerHTML], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(html);
    const link = document.createElement("a");
    link.href = url;
    const basename = location.pathname.split("/").pop();
    link.download = basename && /\.html?$/i.test(basename)
      ? decodeURIComponent(basename) : "manual.html";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  updateSave();
})();
