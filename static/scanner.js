// static/scanner.js

// Asume que ya has incluido <script src="/static/html5-qrcode.min.js"></script>
// y tu plantilla tiene un <div id="reader"></div> y un <button id="stop-btn">Detener escaneo</button>

const html5QrCode = new Html5Qrcode("reader");
let ultimoShipId = null;

const qrConfig = {
  fps: 10,
  qrbox: { width: 300, height: 300 },
  aspectRatio: 16 / 9
};

function startScanning() {
  html5QrCode.start(
    { facingMode: "environment" },
    qrConfig,
    decodedText => {
      // al detectar un QR con texto, lo paramos y procesamos
      html5QrCode
        .stop()
        .then(() => {
          document.getElementById("stop-btn").innerText = "Reanudar escaneo";
          handleDecoded(decodedText);
        })
        .catch(console.error);
    },
    errorMessage => {
      // no hacemos nada mientras no haya QR válido
    }
  ).catch(err => console.error("Error arrancando cámara:", err));
}

function handleDecoded(raw) {
  // tu función de parseo y petición al back
  const { order_id, shipment_id } = parseQr(raw);
  if (!shipment_id) {
    alert("QR inválido, no contiene shipment_id");
    return;
  }
  ultimoShipId = shipment_id;
  fetch("/escanear", {
    method: "POST",
    body: new URLSearchParams({ shipment_id }),
    credentials: "include"
  })
    .then(res => res.ok ? res.json() : Promise.reject(res.status))
    .then(data => {
      // muestra detalle
      document.getElementById("cliente").innerText = data.detalle.cliente;
      const tabla = document.getElementById("tabla-items");
      tabla.innerHTML = "";
      data.detalle.items.forEach(item => {
        const thumb = (item.imagenes?.[0]?.thumbnail) || "https://via.placeholder.com/150";
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td style="text-align:center;padding:0.5rem;border-bottom:1px solid #eee;">
            <img src="${thumb}" width="80" style="border-radius:4px;">
          </td>
          <td style="padding:0.5rem;border-bottom:1px solid #eee;">${item.titulo}</td>
          <td style="padding:0.5rem;border-bottom:1px solid #eee;">${item.sku || ""}</td>
          <td style="padding:0.5rem;border-bottom:1px solid #eee;">${item.variante || ""}</td>
          <td style="padding:0.5rem;border-bottom:1px solid #eee;">${item.cantidad}</td>
        `;
        tabla.appendChild(tr);
      });
      document.getElementById("detalle-pedido").style.display = "block";
      document.getElementById("boton-armar").style.display = "inline-block";
    })
    .catch(e => {
      console.error("Error al escanear:", e);
      alert("No se pudo obtener detalle del pedido");
    });
}

// extraigo order_id / shipment_id del texto escaneado
function parseQr(decoded) {
  let shipment_id = null, order_id = null;
  decoded = decoded.trim();
  if (decoded.startsWith("{")) {
    try {
      const obj = JSON.parse(decoded);
      shipment_id = obj.id || obj.shipment_id || null;
      return { order_id: null, shipment_id };
    } catch {}
  }
  try {
    const url = new URL(decoded);
    const parts = url.pathname.split("/").filter(p => p);
    if (parts[0] === "shipments") shipment_id = parts[1];
    else if (parts[0] === "orders") order_id = parts[1];
    return { order_id, shipment_id };
  } catch {}
  return { order_id: decoded, shipment_id: null };
}

// marcar como armado
function setupArmButton() {
  document.getElementById("boton-armar").addEventListener("click", () => {
    if (!ultimoShipId) return alert("No hay shipment para armar");
    fetch("/armar", {
      method: "POST",
      body: new URLSearchParams({ shipment_id: ultimoShipId }),
      credentials: "include"
    })
      .then(r => r.json())
      .then(resp => {
        if (resp.success) {
          alert("Marcado como armado");
          window.location.reload();
        } else {
          alert(resp.error || "Error al marcar armado");
        }
      })
      .catch(err => {
        console.error("Error /armar:", err);
        alert("No se pudo marcar armado");
      });
  });
}

window.addEventListener("DOMContentLoaded", () => {
  startScanning();
  setupArmButton();

  document.getElementById("stop-btn").addEventListener("click", () => {
    if (html5QrCode._isScanning) {
      html5QrCode.stop().then(() => {
        document.getElementById("stop-btn").innerText = "Reanudar escaneo";
      });
    } else {
      startScanning();
      document.getElementById("stop-btn").innerText = "Detener escaneo";
    }
  });
});
