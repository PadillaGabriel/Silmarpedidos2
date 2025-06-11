// scanner.js

// --- Configuración de elementos ---
const videoEl      = document.createElement('video');
const canvasEl     = document.createElement('canvas');
const ctx          = canvasEl.getContext('2d');
const scanBtn      = document.getElementById('scan-btn');
const stopBtn      = document.getElementById('stop-btn');
const errorMsg     = document.getElementById('error-msg');
const detalleCard  = document.getElementById('detalle-pedido');
const clienteEl    = document.getElementById('cliente');
const tablaItems   = document.getElementById('tabla-items');

// Sonido de aviso
const beep = new Audio('/static/beep.mp3');

// Preparamos el contenedor #reader
const container = document.getElementById('reader');
container.style.position = 'relative';
videoEl.style.cssText = `
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  box-sizing: border-box;
  aspect-ratio: 1/1;
`;
videoEl.autoplay                = true;
videoEl.muted                   = true;
videoEl.playsInline             = true;
videoEl.setAttribute('playsinline','');
videoEl.setAttribute('webkit-playsinline','');
canvasEl.style.display = 'none';
container.append(videoEl, canvasEl);

// --- Funciones de cámara ---
let stream = null;
async function iniciarCamara() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const back = devices.find(d =>
    d.kind === 'videoinput' && /back|rear|environment/i.test(d.label)
  );
  const constraints = back
    ? { deviceId: { exact: back.deviceId } }
    : { facingMode: 'environment' };
  stream = await navigator.mediaDevices.getUserMedia({
    video: { ...constraints, width:{ideal:640}, height:{ideal:480} }
  });
  videoEl.srcObject = stream;
  await videoEl.play();
}

function detenerCamara() {
  if (stream) stream.getTracks().forEach(t => t.stop());
}

// --- Decodificación de un frame ---
async function decodificarFrame() {
  if (!videoEl.videoWidth) return null;
  canvasEl.width  = videoEl.videoWidth;
  canvasEl.height = videoEl.videoHeight;
  ctx.drawImage(videoEl, 0, 0);
  return new Promise(resolve => {
    canvasEl.toBlob(blob => resolve(blob), 'image/jpeg');
  });
}

// --- Lógica de escaneo bajo demanda ---
scanBtn.addEventListener('click', async () => {
  errorMsg.textContent = '';
  detalleCard.style.display = 'none';

  try {
    // arrancamos cámara y esperamos un frame
    await iniciarCamara();
    const blob = await decodificarFrame();
    detenerCamara();

    if (!blob) {
      throw new Error('No se capturó imagen');
    }

    // enviamos al servidor
    const form = new FormData();
    form.append('frame', blob, 'frame.jpg');
    const res = await fetch('/decode-qr', {
      method: 'POST',
      body: form,
      credentials: 'include'
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const json = await res.json();
    console.log('decode-qr ->', json);

    if (!json.data) {
      throw new Error('QR no detectado');
    }

    // llamamos a tu API para obtener detalle
    const id = json.data; // puede ser shipment_id u order_id
    const detalleRes = await fetch(`/api/get_order?shipment_id=${id}`);
    if (!detalleRes.ok) {
      throw new Error(`Detalle HTTP ${detalleRes.status}`);
    }
    const detalleJson = await detalleRes.json();
    console.log('detalle order ->', detalleJson);

    if (!detalleJson.items || detalleJson.items.length === 0) {
      throw new Error('No hay items en el pedido');
    }

    mostrarDetalle(detalleJson);

    // aviso sonoro y visual
    videoEl.style.outline = '5px solid lime';
    setTimeout(() => videoEl.style.outline = '', 500);
    beep.play().catch(() => {});

  } catch (e) {
    detenerCamara();
    console.warn(e);
    errorMsg.textContent = e.message;
  }
});

// botón detener cámara manual
stopBtn.addEventListener('click', () => {
  detenerCamara();
  errorMsg.textContent = 'Escaneo detenido';
});

// --- Pinta en la página el detalle recibido ---
function mostrarDetalle(pedido) {
  clienteEl.textContent = pedido.cliente;
  tablaItems.innerHTML = ''; // limpio tabla

  pedido.items.forEach(it => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td style="padding:0.5rem; border-bottom:1px solid #ccc;">
        <img src="${it.imagenes[0].thumbnail}" alt="" style="height:50px;">
      </td>
      <td style="padding:0.5rem; border-bottom:1px solid #ccc;">${it.titulo}</td>
      <td style="padding:0.5rem; border-bottom:1px solid #ccc;">${it.sku}</td>
      <td style="padding:0.5rem; border-bottom:1px solid #ccc;">${it.variante}</td>
      <td style="padding:0.5rem; border-bottom:1px solid #ccc;">${it.cantidad}</td>
    `;
    tablaItems.append(tr);
  });

  detalleCard.style.display = 'block';
}
