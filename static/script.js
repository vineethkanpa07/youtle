const MAX_GUESSES = 6;
let names = [];
let guessedNames = [];
let guessCount = 0;
let gameOver = false;
let mode = "daily";

const input = document.getElementById('guessInput');
const sugg = document.getElementById('suggestions');
const board = document.getElementById('board');
const guessCountEl = document.getElementById('guessCount');
const messageEl = document.getElementById('message');
const revealEl = document.getElementById('answerReveal');
const newGameBtn = document.getElementById('newGameBtn');

fetch('/api/names').then(r => r.json()).then(list => { names = list; });

input.addEventListener('input', () => {
  const v = input.value.trim().toLowerCase();
  sugg.innerHTML = '';
  if (!v) { sugg.style.display = 'none'; return; }
  const matches = names.filter(n => n.toLowerCase().includes(v) && !guessedNames.includes(n)).slice(0, 6);
  if (matches.length === 0) { sugg.style.display = 'none'; return; }
  matches.forEach(m => {
    const div = document.createElement('div');
    div.textContent = m;
    div.onclick = () => submitGuess(m);
    sugg.appendChild(div);
  });
  sugg.style.display = 'block';
});

input.addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    const v = input.value.trim();
    const match = names.find(n => n.toLowerCase() === v.toLowerCase());
    if (match) submitGuess(match);
  }
});

document.addEventListener('click', e => {
  if (!e.target.closest('.search-wrap')) sugg.style.display = 'none';
});

newGameBtn.addEventListener('click', () => {
  fetch('/api/new-game', { method: 'POST' }).then(() => {
    mode = 'practice';
    guessedNames = [];
    guessCount = 0;
    gameOver = false;
    input.disabled = false;
    input.value = '';
    sugg.style.display = 'none';
    board.innerHTML = '';
    guessCountEl.textContent = MAX_GUESSES;
    messageEl.textContent = '';
    revealEl.textContent = '';
    input.focus();
  });
});

function cellClass(status) {
  return status === 'hit' ? 'hit' : 'miss';
}

function arrowSymbol(arrow) {
  if (arrow === 'up') return ' ↑';
  if (arrow === 'down') return ' ↓';
  return '';
}

async function submitGuess(name) {
  if (gameOver) return;
  const res = await fetch('/api/guess', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, mode })
  });
  if (!res.ok) return;
  const g = await res.json();

  guessedNames.push(name);
  guessCount += 1;
  input.value = '';
  sugg.style.display = 'none';
  renderRow(g);
  guessCountEl.textContent = Math.max(0, MAX_GUESSES - guessCount);

  if (g.won) {
    endGame(true, g.name);
  } else if (guessCount >= MAX_GUESSES) {
    endGame(false, null);
  }
}

function renderRow(g) {
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td class="name">${g.name}</td>
    <td class="${cellClass(g.subs.status)}">${g.subs.value}M${arrowSymbol(g.subs.arrow)}</td>
    <td class="${cellClass(g.country.status)}">${g.country.value}</td>
    <td class="${cellClass(g.gender.status)}">${g.gender.value}</td>
    <td class="${cellClass(g.started.status)}">${g.started.value}${arrowSymbol(g.started.arrow)}</td>
    <td class="${cellClass(g.videos.status)}">${g.videos.value}${arrowSymbol(g.videos.arrow)}</td>
    <td class="${cellClass(g.niche.status)}">${g.niche.value}</td>
  `;
  board.appendChild(tr);
}

function endGame(won, answerName) {
  gameOver = true;
  input.disabled = true;
  messageEl.textContent = won ? "GOT IT 🎯" : "OUT OF GUESSES";
  if (!won) {
    fetch(`/api/reveal?mode=${mode}`).then(r => r.json()).then(data => {
      revealEl.textContent = "Today's creator: " + data.name;
    });
  }
}