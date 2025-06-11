// static/scanner.js
const beep = new Audio('/static/beep.mp3');
const videoEl  = document.createElement('video');
videoEl.autoplay     = true;
videoEl.playsInline   = true;
videoEl.muted        = true;
videoEl.disablePictureInPicture = true;
videoEl.setAttribute('playsinline', '');
videoEl.setAttribute('webkit-playsinline', '');
videoEl.style.cssText = `
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
`;

canvasEl.style.display = 'none';
preview.style.cssText = `
  position: absolute;
  top: 0; right: 0;
  width: 80px; height: 60px;
  border: 2px solid red;
  z-index: 9999;
`;
document.getElementById('reader').append(videoEl, canvasEl, preview);

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

async function escanearFrame() {
  if (!videoEl.videoWidth) return;
  // dibujar
  canvasEl.width  = videoEl.videoWidth;
  canvasEl.height = videoEl.videoHeight;
  ctx.drawImage(videoEl, 0, 0);
  // debug: mostrar miniatura
  preview.src = canvasEl.toDataURL('image/jpeg', 0.3);

  // enviar al servidor
  canvasEl.toBlob(async blob => {
    const form = new FormData();
    form.append('frame', blob, 'frame.jpg');
    console.log('enviando frame...', blob);
    const res = await fetch('/decode-qr', {
      method: 'POST', body: form, credentials: 'include'
    });
    if (!res.ok) {
      console.warn('HTTP', res.status);
      return;
    }
    const json = await res.json();
    console.log('respuesta decode-qr:', json);
    if (json.data) {
  // aviso visual:
  videoEl.style.border = '5px solid lime';
  setTimeout(()=> videoEl.style.border = '', 500);
  // aviso sonoro:
  beep.play().catch(()=>{});
  escanear(json.data);
}

document.addEventListener('DOMContentLoaded', () => {
  iniciarCamara().catch(e => console.error('Cámara:', e));
  setInterval(escanearFrame, 800);

  document.getElementById('stop-btn').onclick = () => {
    videoEl.srcObject?.getTracks().forEach(t => t.stop());
  };
});
