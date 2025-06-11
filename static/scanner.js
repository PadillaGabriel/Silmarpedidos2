// scanner.js

// Sonido de aviso
const beep = new Audio('/static/beep.mp3');

// Elementos de vídeo y canvas
const videoEl  = document.createElement('video');
const canvasEl = document.createElement('canvas');
const ctx      = canvasEl.getContext('2d');

// Configuración inicial (igual que antes)
videoEl.autoplay                = true;
videoEl.muted                   = true;
videoEl.playsInline             = true;
videoEl.disablePictureInPicture = true;
videoEl.disableRemotePlayback   = true;
videoEl.setAttribute('playsinline','');
videoEl.setAttribute('webkit-playsinline','');
videoEl.style.cssText = `
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  box-sizing: border-box;
  aspect-ratio: 1/1;
`;
canvasEl.style.display = 'none';

const container = document.getElementById('reader');
container.style.position = 'relative';
container.append(videoEl, canvasEl);

// Botones y mensajes
const scanBtn    = document.getElementById('scan-btn');
const stopBtn    = document.getElementById('stop-btn');
const errorMsg   = document.getElementById('error-msg');

// Variables de estado
let stream = null;

async function iniciarCamara() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const back = devices.find(d =>
    d.kind === 'videoinput' && /back|rear|environment/i.test(d.label)
  );
  const constraintVideo = back
    ? { deviceId: { exact: back.deviceId } }
    : { facingMode: 'environment' };

  stream = await navigator.mediaDevices.getUserMedia({
    video: { ...constraintVideo, width:{ideal:640}, height:{ideal:480} }
  });
  videoEl.srcObject = stream;
  await videoEl.play();
}

function detenerCamara() {
  if (stream) {
    stream.getTracks().forEach(t => t.stop());
    stream = null;
  }
}

// Dibuja un frame y lo envía al servidor UNA vez
async function escanearUnaVez() {
  if (!videoEl.videoWidth) {
    errorMsg.textContent = 'No se pudo acceder a la cámara.';
    return;
  }
  errorMsg.textContent = '';

  canvasEl.width  = videoEl.videoWidth;
  canvasEl.height = videoEl.videoHeight;
  ctx.drawImage(videoEl, 0, 0);

  canvasEl.toBlob(async blob => {
    const form = new FormData();
    form.append('frame', blob, 'frame.jpg');
    try {
      const res = await fetch('/decode-qr', {
        method: 'POST',
        body: form,
        credentials: 'include'
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (!json.data) throw new Error('QR no detectado');
      // marcado visual
      videoEl.style.outline = '5px solid green';
      setTimeout(() => videoEl.style.outline = '', 500);
      beep.play().catch(() => {});
      mostrarDetalle(json.data);
      detenerCamara();
    } catch (e) {
      errorMsg.textContent = e.message;
    }
  }, 'image/jpeg');
}

// Llena la sección de detalle con la respuesta del backend
function mostrarDetalle(pedido) {
  document.getElementById('detalle-pedido').style.display = 'block';
  document.getElementById('cliente').textContent = pedido.buyer_name;
  const tbody = document.getElementById('tabla-items');
  tbody.innerHTML = '';
  pedido.items.forEach(item => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><img src="${item.picture_url}" style="width:50px;"></td>
      <td>${item.title}</td>
      <td>${item.sku}</td>
      <td>${item.variation}</td>
      <td>${item.quantity}</td>
    `;
    tbody.append(tr);
  });
  document.getElementById('boton-armar').style.display = 'block';
}

// Listeners
scanBtn.addEventListener('click', async () => {
  await iniciarCamara();
  escanearUnaVez();
});

stopBtn.addEventListener('click', () => {
  detenerCamara();
  errorMsg.textContent = '';
});
