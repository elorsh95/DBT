# התקנה בפעם הראשונה

קלוד מתקין, המשתמש רק מאשר.

**מה נכנס לאן** (אומרים את זה למשתמש בכנות, לפני שמתחילים):
- הספריות של הסקיל וקובץ ההגדרות: בתיקייה אחת בבית של המשתמש, `~/.motion-studio` (בווינדוס `C:/Users/<שם>/.motion-studio`).
- הדפדפן שמצלם את הפריימים (Chromium, בערך 150MB): בתיקיית המטמון של Playwright. במק `~/Library/Caches/ms-playwright`, בווינדוס `%LOCALAPPDATA%\ms-playwright`, בלינוקס `~/.cache/ms-playwright`.
- Python, אם הוא לא מותקן: מותקן למחשב כולו. במק דרך הכלים של אפל (Command Line Tools) או Homebrew, בווינדוס דרך winget.

להסרה: מוחקים את `~/.motion-studio` ואת תיקיית ה-ms-playwright. את Python משאירים (תוכנות אחרות עשויות להשתמש בו).

## איך מדברים עם המשתמש

שלב אחד בכל פעם: משפט אחד שמסביר מה עכשיו ולמה, פקודה אחת, ואז מראים שזה עבד. בלי מונחים כמו venv, PATH או pip. "סביבה נפרדת", "הכלי", "הדפדפן שמצלם את הפריימים".

פתיחה לדוגמה:
> "לפני האנימציה הראשונה צריך להתקין פעם אחת כמה כלים חינמיים: Python, דפדפן שמצלם את הפריימים, וכלי שמחבר אותם לסרטון. הספריות נכנסות לתיקייה אחת בשם .motion-studio, הדפדפן לתיקיית המטמון שלו, ואם אין לכם Python הוא יותקן למחשב. לוקח כמה דקות. להתחיל?"

את מערכת ההפעלה מזהים מהסביבה, לא שואלים.

## שלב 1: Python (3.9 ומעלה)

**מק:** קודם בודקים בשקט, בלי להפעיל שום חלון:
```bash
xcode-select -p >/dev/null 2>&1 && echo tools-yes || echo tools-no
ls /opt/homebrew/bin/python3 /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/*/bin/python3 2>/dev/null
```
- **אם הכלים של אפל חסרים ואין Python אחר:** אל תריצו `python3 --version` ישר. ב-Mac בלי Python, הפקודה `python3` היא קיצור של אפל שפותח חלון "The python3 command requires the command line developer tools". אומרים למשתמש מראש:
  > "עכשיו ייפתח חלון של אפל שמבקש להתקין את כלי הפיתוח. לחצו Install (לא Get Xcode), אשרו את הרישיון, ותחכו עד שכתוב שההתקנה הסתיימה. זה לוקח 5 עד 15 דקות."

  ואז `xcode-select --install`. כשהמשתמש אומר שזה נגמר, ממשיכים. אם יש Homebrew, `brew install python` הוא חלופה בלי החלון.
- **אחרת:** `python3 --version` (או הנתיב שנמצא). 3.9 ומעלה: ממשיכים.

**ווינדוס** (Claude Code רץ ב-Git Bash):
```bash
py --version || python --version
```
- `python` שפותח את Microsoft Store או לא מחזיר כלום הוא קיצור דרך ריק, לא Python. משתמשים ב-`py`.
- לא קיים:
```bash
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements --disable-interactivity
```
  אחרי ההתקנה `py` מזוהה רק בטרמינל חדש. אם לא מזוהה, הנתיב המלא הוא בדרך כלל `"$LOCALAPPDATA/Programs/Python/Python312/python.exe"`.

## שלב 2: סביבה נפרדת בתיקייה אחת

**מק:**
```bash
python3 -m venv ~/.motion-studio/venv
PY=~/.motion-studio/venv/bin/python
```

**ווינדוס:**
```bash
py -m venv "$HOME/.motion-studio/venv"
PY="$HOME/.motion-studio/venv/Scripts/python.exe"
```

## שלב 3: הספריות

```bash
"$PY" -m pip install --upgrade pip
"$PY" -m pip install playwright numpy pillow imageio-ffmpeg
```
- `playwright` מפעיל את הדפדפן שמצלם, `numpy` לסאונד, `pillow` לגיליונות הבדיקה, `imageio-ffmpeg` מביא איתו ffmpeg מוכן.

## שלב 4: הדפדפן שמצלם את הפריימים

```bash
"$PY" -m playwright install chromium
```
הורדה של בערך 150MB, דקה עד שלוש. אם נראה תקוע, מחכים.

## שלב 5: ffmpeg

```bash
ffmpeg -version
```
- מותקן: `render.py` ישתמש בו.
- לא מותקן: לא צריך להתקין כלום. `imageio-ffmpeg` משלב 3 כבר הביא אחד, ו-`render.py` מוצא אותו לבד. מוודאים:
```bash
"$PY" -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
```

## שלב 6: בדיקת אמת, ורק אז קובץ ההגדרות

קודם הוכחה, אחר כך רישום. בונים פרויקט בדיקה קטן בתיקייה זמנית ומרנדרים ממנו פריים אחד:

```bash
T="$HOME/.motion-studio/selftest"; rm -rf "$T"; mkdir -p "$T"
S="<נתיב תיקיית הסקיל>/assets"
cp "$S/engine/core.js" "$S/template/index.html" "$S/template/scene.js" "$S/render.py" "$S/audio.py" "$T/"
cp -r "$S/fonts" "$T/fonts"
cd "$T" && "$PY" render.py stills 1.0
```
מסתכלים על `stills/t-01.000.png` (כלי Read): צריכה להופיע המילה "שלום" בלבן על רקע כהה, בפונט עבה. יצא? מוחקים את `$T` וכותבים את **`~/.motion-studio/state.json`** (בתיקיית הבית, לא בתיקיית הסקיל: תיקיית הסקיל מתאפסת בהתקנה מחדש, וב-Cowork היא עשויה להיות לקריאה בלבד):

```json
{
  "setup_done": true,
  "os": "mac",
  "python": "/Users/<user>/.motion-studio/venv/bin/python",
  "ffmpeg": "system",
  "checked": "2026-09-27"
}
```
- `python`: נתיב מלא, אחרי הרחבה של `~` ו-`$HOME`. בווינדוס עם לוכסנים רגילים: `C:/Users/<user>/.motion-studio/venv/Scripts/python.exe`.
- `ffmpeg`: `"system"` או `"imageio-ffmpeg"`.
- `checked`: התאריך של היום.

ולמשתמש:
> "הכל מותקן ועובד. מעכשיו ניגשים ישר לאנימציה."

וממשיכים ישר לשלב בחירת הסגנון.

## Cowork

Cowork מריץ את העבודה במחשב וירטואלי של לינוקס. אותם שלבים, עם `python3` ועם:
```bash
"$PY" -m playwright install --with-deps chromium
```
אם ההתקנה נחסמת (אין הרשאה או אין רשת), אומרים למשתמש בשורה אחת שהרינדור צריך את Claude Code על המחשב שלו, ומפנים ל-README.txt.

## תקלות נפוצות

| תקלה | פתרון |
|---|---|
| `externally-managed-environment` | מתקינים רק בתוך הסביבה (`"$PY" -m pip`), אף פעם לא ב-pip של המערכת |
| `playwright install` נכשל ברשת | מנסים שוב. ברשת ארגונית: `HTTPS_PROXY` |
| בווינדוס `py` לא מזוהה אחרי ההתקנה | נתיב מלא (שלב 1), או לסגור ולפתוח את Claude Code. אפשר לרשום בינתיים `"setup_done": false, "step": 2` ב-`~/.motion-studio/state.json` כדי להמשיך מאותו מקום |
| `Executable doesn't exist` בזמן רינדור | הדפדפן לא הותקן בסביבה הזאת: שלב 4 שוב |
| הפריים יוצא ריק או בלי עברית | חסרה תיקיית `fonts` בפרויקט, או שהדף נפל: `render.py` מדפיס `PAGEERROR` |
| `~/.motion-studio/state.json` אומר מותקן אבל `python` לא קיים | `setup_done: false` וחוזרים לשלב 1 |
| במק נפתח חלון של אפל באמצע | זה החלון של שלב 1: Install, מחכים, וממשיכים |
