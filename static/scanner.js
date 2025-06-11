// static/scanner.js

const videoEl  = document.createElement('video');
const canvasEl = document.createElement('canvas');
const ctx      = canvasEl.getContext('2d');

// ocultar y meter dentro de #reader para conservar tu CSS
videoEl.style.display  = 'none';
canvasEl.style.display = 'none';
document.getElementById('reader').append(videoEl, canvasEl);

async function iniciarCamara() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const back = devices.find(d=>d.kind==='videoinput' && /back|rear|environment/i.test(d.label));
  const constraints = {
    video: back
      ? { deviceId: { exact: back.deviceId } }
      : { facingMode: 'environment' }
  };
  const stream = await navigator.mediaDevices.getUserMedia(constraints);
  videoEl.srcObject = stream;
  await videoEl.play();
}

async function escanearFrame() {
  if (!videoEl.videoWidth) return;
  canvasEl.width  = videoEl.videoWidth;
  canvasEl.height = videoEl.videoHeight;
  ctx.drawImage(videoEl, 0, 0);
  const blob = await new Promise(r=>canvasEl.toBlob(r,'image/jpeg'));
  const form = new FormData();
  form.append('frame', blob, 'frame.jpg');
  const res = await fetch('/decode-qr', {
    method: 'POST', body: form, credentials: 'include'
  });
  const json = await res.json();
  if (json.data) {
    scanner.stop?.();           // si sigues usando html5-qrcode
    escanear(json.data);        // tu función existente
  }
}

document.addEventListener('DOMContentLoaded', ()=>{
  iniciarCamara().catch(e=>console.error(e));
  // cada 800 ms lee un frame
  setInterval(escanearFrame, 800);

  // reuso tus listeners
  document.getElementById('stop-btn').onclick = () => {
    const tracks = videoEl.srcObject?.getTracks()||[];
    tracks.forEach(t=>t.stop());
  };
});
