# SATRI Arcade — Remote Question Bank System

Question haru **HTML ma hard-code nagari link bata load** hune system.
20+ players le kheldeo pani **same question repeat hundaianna** (pool sakepachi matra).

## Files

| File | Kaam |
|---|---|
| `index.html` | Update gareko game (sabai built-in questions + naya system) |
| `questions.json` | Online/local question bank (naya questions yaha thapne) |

## System kasari kaam garchha (3-tier fallback)

```
1) REMOTE_QUESTIONS_URL   → online link (GitHub raw / hosting / CDN)     ┐
2) ./questions.json       → game ko same folder ma (server bata khelda)  ├─ juni pahilo payo tyo use
3) Built-in questions     → HTML bhitrai ko (offline pani game chalcha)  ┘
```

- **Merge rule:** objective (ra bug lines) same bhaye duplicate — naya le purano replace garchha
- **No-repeat memory:** browser (localStorage) le dekheko questions yaad rakhcha —
  player le pool ko **sabai** questions dekhesamma same question repeat hunchha
- Menu screen ma live status dekhinchha: `📚 Question bank — SQL: 40 (32 new) · ...`
- `↺ Reset my question history` click garda memory reset hunchha

## Questions kasari thapne (company ma)

### Option A — GitHub (free, sabai bhanda sajilo) ⭐

1. GitHub ma naya **public** repo banaunus (e.g. `satri-questions`)
2. `questions.json` upload garnus
3. Raw link copy garnus: file kholera **Raw** button thichda (ya `?raw=true`)
   → `https://raw.githubusercontent.com/<username>/satri-questions/main/questions.json`
4. `index.html` ma yo line paryauna basnus:
   ```javascript
   const REMOTE_QUESTIONS_URL = "https://raw.githubusercontent.com/<username>/satri-questions/main/questions.json";
   ```
5. **Naya question thapda:** GitHub ma `questions.json` edit → Commit bas.
   Sabai player lai turantai naya questions (page refresh matra)!

> Note: Yo sandbox ko GitHub le bot-account le matra access dinchha, tai maile
> tapaiko account ma repo banauna sakina. Tapaiko aafno GitHub ma 2 min ma
> banaunus — steps mathi chha.

### Option B — Same folder ma

`questions.json` lai `index.html` sanga ekai folder ma rakhne (server/localhost bata
kholda automatic load hunchha — REMOTE_QUESTIONS_URL khali nai chaleko chha).

> `file://` bata direct HTML khole local fetch browser le block garchha —
> tesi bela online link ya built-in fallback use hunchha.

## questions.json ko format

```json
{
  "sql": [
    {
      "objective": "Question text...",
      "options": ["galat", "SAHI", "galat", "galat"],
      "correctIndex": 1
    }
  ],
  "git": [ "... same format ..." ],
  "words": ["nayaword", "arkoword"],
  "bugLabels": { "nayofield": "Naya Course ko Name" },
  "bug": {
    "python": [
      {
        "difficulty": "easy | medium | hard",
        "lines": ["line 1", "line 2", "line 3"],
        "bugIndex": 1,
        "explanation": "Bug ke ho, kina fix garna parne explanation"
      }
    ]
  }
}
```

- `correctIndex` — options ma sahi answer kun index ma chha (0,1,2,3) —
  game le options afai shuffle garchha, tai position j bata pani hunchha
- `bugIndex` — `lines` array ma bug kun line ma chha (0 bata count)
- **Naya bug field** thayo bhane tyo automatic Bug Hunter menu ma dekhinchha

## Yo bank ma kati chha?

| Pool | Built-in | + JSON | Total |
|---|---|---|---|
| SQL Master | 20 | 20 | **40** |
| Git Master | 20 | 16 | **36** |
| Bug Hunter | 155 (25 fields) | 20 + naya *C++* field | **175 (26 fields)** |
| Word Scramble | 62 | 40 | **102** |

## Testing (yo sandbox ma verify gariyeko)

- ✅ JSON valid, JavaScript syntax valid
- ✅ Merge pachi duplicate hoina (re-apply garda pani count same)
- ✅ 40 draws = 40 unique (pool sake samma repeat nahuney)
- ✅ Player 1 le 10 question dekhepachi, Player 2 (ekai browser) lai tyo 10 dekhina — 0 overlap
- ✅ Reset history kaam garchha
- ✅ Naya field (C++) JSON bata add hunchha
