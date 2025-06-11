// Sonido de aviso
const beep = new Audio('/static/beep.mp3');

// Vídeo y canvas
const videoEl  = document.createElement('video');
const canvasEl = document.createElement('canvas');
const ctx      = canvasEl.getContext('2d');

// Estilos del vídeo
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
  aspect-ratio: 16/9;
`;

// Canvas oculto
canvasEl.style.display = 'none';

// Montamos en el contenedor
const container = document.getElementById('reader');
container.style.position = 'relative';
container.append(videoEl, canvasEl);

// Estado
let streaming = true;

// Inicia la cámara tras cargar
async function iniciarCamara() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const back = devices.find(d => d.kind==='videoinput' && /back|rear|environment/i.test(d.label));
  const constraintVideo = back
    ? { deviceId: { exact: back.deviceId } }
    : { facingMode: 'environment' };

  const stream = await navigator.mediaDevices.getUserMedia({
    video: { ...constraintVideo, width:{ideal:640}, height:{ideal:480} }
  });
  videoEl.srcObject = stream;
  await videoEl.play();
}

// Detiene la cámara
function detenerCamara() {
  streaming = false;
  videoEl.srcObject?.getTracks().forEach(t => t.stop());
}

// Escanea un solo frame
async function escanearFrame() {
  clearError();
  if (!streaming || !videoEl.videoWidth) return showError('La cámara no está lista');

  canvasEl.width  = videoEl.videoWidth;
  canvasEl.height = videoEl.videoHeight;
  ctx.drawImage(videoEl, 0, 0);

  return new Promise(resolve => {
    canvasEl.toBlob(async blob => {
      const form = new FormData();
      form.append('frame', blob, 'frame.jpg');
      try {
        const res  = await fetch('/decode-qr', { method:'POST', body:form, credentials:'include' });
        if (!res.ok) return showError(`HTTP ${res.status}`);
        const json = await res.json();
        if (json.error) return showError(json.error);

        // Éxito: dibujamos outline, sonido y llamada a tu lógica
        videoEl.style.outline = '5px solid lime';
        setTimeout(() => videoEl.style.outline = '', 500);
        beep.play().catch(()=>{});
        escanear(json.data.shipment_id);
        detenerCamara();
      } catch(e) {
        showError('Error interno');
        console.error(e);
      }
      resolve();
    }, 'image/jpeg');
  });
}

function showError(msg) {
  document.getElementById('error-msg').innerText = msg;
}
function clearError() {
  document.getElementById('error-msg').innerText = '';
}

// Arranque al cargar la página
document.addEventListener('DOMContentLoaded', () => {
  iniciarCamara().catch(e => showError('No se pudo acceder a la cámara'));

  document.getElementById('scan-btn')
    .addEventListener('click', () => escanearFrame());

  document.getElementById('stop-btn')
    .addEventListener('click', detenerCamara);

  // Aquí enlazas tu input file y búsqueda manual…
});
