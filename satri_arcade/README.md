# SATRI Arcade — Remote Question Bank (500+ per section)

Questions **hard-code nagari** `questions.json` bata load hunchan — repo ma push
garesi Netlify ma automatic live. **Folder ko naam kayam farak pardaina**
(e.g. `SATRI GAME` folder ma rakhda pani kaam garchha) — bas yo duita file
**ekai folder** ma bhaye pugchha:

```
your-folder/
├── index.html        ← game (yehi file sabai thauma deploy/push garne)
├── questions.json    ← question bank (500+ per section)  ← index.html sanga EKAI folder ma!
├── generate_bank.py  ← (optional) questions feri banaune/add garne script
└── README.md
```

## 📊 Kati kati questions chhan? (live verified counts)

| Game | Questions | Kahan bata |
|---|---|---|
| **SQL Master** | **519 MCQs** | generated (500) + built-in |
| **Git Master** | **519 MCQs** | generated (500) + built-in |
| **Word Scramble / Speed Typing** | **738 words** (shared) | generated (688) + built-in |
| **Bug Hunter** | **4,115 unique challenges — हरेक field मा 500+** | shared language pools |
| Color Flash | ∞ (engine generates) | random color/word combos |
| Memory Grid | ∞ (engine generates) | random tile sequences |
| Flash Recall | ∞ (engine generates) | random numbers, growing digits |

### Bug Hunter — field-wise (26 fields, सबै 500+)

| Field | Questions | Field | Questions |
|---|---|---|---|
| Full-Stack | 584 | IoT | 525 |
| MERN | 523 | Smart Home/Industrial IoT | 1,025 |
| React.js | 592 | Cybersecurity | 513 |
| Next.js | 545 | QA | 575 |
| Laravel | 602 | DevOps | 504 |
| Django | 666 | Digital Marketing | 505 |
| WordPress | 654 | Social Media Mgmt | 505 |
| Flutter | 504 | Content Marketing | 505 |
| Cross-Platform | 520 | Project-Based IT | 850 |
| UI/UX Design | 507 | IT Internship | 850 |
| Graphics Design | 505 | Gen AI | 565 |
| Product Design | 505 | C++ (new field) | 520 |
| Python | 544 | Data Analytics | 725 |

**Kasari 4,115 le 26 fields × 500+ banchha?** Shared language pools — e.g.
JavaScript pool (305) fullstack/mern/react/wordpress/laravel fields sabai ma
share hunchha. Har challenge JSON ma **ekai choti** store hunchha → file sano
(~1 MB) rahanchha.

## 🔗 Sources — questions katai bata liyeko? (IMPORTANT)

### Yo bank ma (questions.json):
1. **Programmatically generated** — `generate_bank.py` le template-based
   generate gareko **original questions** (deterministic seed `20260822`).
   Yo project ko own content ho — free to use, kunai license issue chhaina.
   Har SQL/Git MCQ ra bug challenge template bata parametrize bhayera banyo,
   tesaile 500+ unique questions bana.
2. **v1 curated set** — pahile ko hand-written questions (index.html bhitra
   built-in fallback ma aajai chhan).

### Public sources (verify gareko — bhavi ma thapna milne):

| Source | Questions | Link | Note |
|---|---|---|---|
| OpenTDB | Computers: **192** (live-verified) | opentdb.com | Free, no key, CORS ok — general tech trivia |
| QuizAPI.io | ~hundreds | quizapi.io | Free API key chahinchha — Code/Docker/MySQL/Linux categories |
| OpenTriviaQA | 48,000+ | github.com/uberspot/OpenTriviaQA | Static dataset, science-technology category |
| devops-exercises | 3,000+ Q&A | github.com/bregman-arie/devops-exercises | Open-ended (not MCQ) — convert garnu parne |

**Sachai kura:** "correct SQL query chuney" / "bug line chuney" format ma
public API **chhaina** — tesaile yo system banyo. Public sources bata
thapna chahyo bhane trivia-style naya "Tech Trivia" mode banauna sakinchha.

## ⚙️ Kasari kaam garchha (3-tier)

```
1) ./questions.json (same folder)  ← sabai bhanda sajilo: index.html sanga rakhne, BAS!
2) REMOTE_QUESTIONS_URL            ← optional: kunai pani online JSON link
3) Built-in questions              ← offline fallback (game kahilyo bhastrindaina)
```

- **Merge rule:** same objective/lines = duplicate → naya le replace
- **No-repeat memory (localStorage):** player le SABAI questions dekhesamma
  same question repeat hunchha. 20+ jana ekai device ma kheldeo pani
  **arko player lai unseen questions matra** (test-verified: 0 overlap)
- Menu ma live status: `📚 Question bank — SQL: 519 (519 new) · ...`
- `↺ Reset my question history` — memory reset

## 🛠️ Questions thapne / regenerate garne

```bash
python3 generate_bank.py   # → naya questions.json (seed 20260822)
```

- Naya questions manual thapna: `questions.json` ma `sql`/`git`/`words`
  array ma item thapne — duplicate automatic hataunchha
- **Naya Bug Hunter field:** `bugLabels` ma label + `bug` ma challenges thapne
- Pool targets/math tune garna script edit garne

## 🚀 Netlify deploy (tapaiko repo)

1. `index.html` + `questions.json` repo root ma push garne
2. Bas! Netlify same-origin load garchha — **kunai config chahindaina**
3. (Optional) External link bata pani: `REMOTE_QUESTIONS_URL` set garne
   index.html ma — e.g. `https://satrigames.netlify.app/questions.json`

## ✅ Testing (yo sandbox ma verified)

- JSON valid · JS syntax valid · MCQs 4-unique-options + valid correctIndex
- All 26 fields 500+ after merge · bugIndex range valid
- 3 rounds play = 3 unique questions · player 2 overlap = 0
