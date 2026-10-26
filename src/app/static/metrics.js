// Страница метрик: таблицы по группам и распределения решений и грейдов.
const $ = (id) => document.getElementById(id);

function distHtml(rows, labelKey) {
  if (!rows.some((r) => r.count)) return `<p class="empty">Пока нет оценённых заявок.</p>`;
  return rows.map((r) => `
    <span>${esc(r[labelKey])}</span>
    <span class="bar"><span style="width:${(r.share || 0) * 100}%"></span></span>
    <span class="n">${r.count}</span>`).join("");
}

async function load() {
  const m = await api("GET", "/bank/metrics");
  $("lead").textContent = `Считаются по всем заявкам в базе: ${m.applications_total}. Модель: ${m.model_versions.join(", ") || "нет оценок"}. Как читать каждую метрику — в docs/metrics.md.`;
  $("groups").innerHTML = m.groups.map((g) => `
    <section>
      <h2>${esc(g.title)}</h2>
      <table class="mtable">${g.metrics.map((x) => `
        <tr><td><strong>${esc(x.label)}</strong><span class="why">${esc(x.why)}</span>
          <span class="formula">${esc(x.formula)}</span></td>
          <td class="val">${esc(x.display)}</td></tr>`).join("")}
      </table>
    </section>`).join("");
  $("decisions").innerHTML = distHtml(m.decisions, "label");
  $("grades").innerHTML = distHtml(m.grades.map((g) => ({ ...g, label: "Грейд " + g.grade })), "label");
}

load().catch((e) => showError($("err"), e));
