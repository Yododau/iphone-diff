let mode = "profit"; // profit | loss

function yen(n){
  const sign = n > 0 ? "+" : "";
  return sign + new Intl.NumberFormat("ja-JP").format(n) + "円";
}

async function load(){
  const [diffRes, metaRes] = await Promise.all([
    fetch("./data/diff.json", { cache: "no-store" }),
    fetch("./data/meta.json", { cache: "no-store" }),
  ]);

  const items = await diffRes.json();
  const meta = await metaRes.json();

  document.getElementById("meta").textContent = `更新：${meta.generated_at_jst || "-"}`;

  const list = document.getElementById("list");
  list.innerHTML = "";

  const filtered = items
    .filter(x => mode === "profit" ? x.diff > 0 : x.diff < 0)
    .sort((a,b) => b.diff - a.diff);

  filtered.forEach(x => {
    const div = document.createElement("div");
    div.className = "row " + (x.diff > 0 ? "profit" : "loss");
    div.innerHTML = `
      <div class="model">${x.model} ${x.capacity || ""}</div>
      <div class="diff">${yen(x.diff)}</div>
    `;
    list.appendChild(div);
  });
}

function setMode(next){
  mode = next;
  document.getElementById("btnProfit").classList.toggle("active", mode==="profit");
  document.getElementById("btnLoss").classList.toggle("active", mode==="loss");
  load();
}

document.getElementById("btnProfit").addEventListener("click", ()=>setMode("profit"));
document.getElementById("btnLoss").addEventListener("click", ()=>setMode("loss"));

load();
