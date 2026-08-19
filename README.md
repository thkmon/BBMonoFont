# BB Mono Font

IBM Plex Mono의 라틴 글리프와 한글/CJK 글리프를 결합한 코딩용 고정폭 글꼴 모음(Font collection)입니다.
영문 한 글자의 advance는 600, 한글 한 글자의 advance는 1200으로 고정되어
터미널과 편집기에서 정확한 **영문 1칸 : 한글 2칸** 격자를 제공합니다.

## 폰트 종류

| 패밀리 | 라틴 | 현대 한글 | 한자·확장 자모·전각 문자 |
|---|---|---|---|
| **BB Mono I** | IBM Plex Mono | IBM Plex Sans KR | Sarasa Mono K |
| **BB Mono S** | IBM Plex Mono | Sarasa Mono K | Sarasa Mono K |

각 패밀리는 Regular와 Bold를 제공합니다.

- [BBMono-I-Regular.ttf](BBMonoFont/fonts/BBMono-I-Regular.ttf)
- [BBMono-I-Bold.ttf](BBMonoFont/fonts/BBMono-I-Bold.ttf)
- [BBMono-S-Regular.ttf](BBMonoFont/fonts/BBMono-S-Regular.ttf)
- [BBMono-S-Bold.ttf](BBMonoFont/fonts/BBMono-S-Bold.ttf)

## 설계 원칙

- IBM Plex Mono의 라틴 윤곽, 리가처, 힌팅 기반, 600-unit 폭을 유지합니다.
- 현대 한글 11,172자, 한자, 전각 문자의 폭은 1200으로 통일합니다. Unicode에서
  실제 반각(Halfwidth)으로 정의된 문자는 영문과 같은 600 폭을 유지합니다.
- 기본 한자 U+4E00–U+9FFF 20,992자, 한글 자모, CJK 문장부호 및 전각/반각
  문자를 포함해 선택된 CJK 코드 포인트 32,904자를 제공합니다.
- 한글/CJK 윤곽은 1200-unit 셀 안에서 글자별로 가로 중앙 정렬합니다.
- 가로와 세로 배율을 독립 적용해 한글이 납작해 보이는 현상을 완화합니다.
- 완성형 한글뿐 아니라 자모 입력도 동작하도록 11,172개의 `ccmp` 조합 규칙을 추가합니다.
- 작은 Windows 편집기 크기를 위해 라틴 글리프에는 `ttfautohint`를 적용하고,
  한글/CJK 글리프에는 비율 왜곡이 없는 fallback scaling을 적용합니다.

사용 배율은 다음과 같습니다.

| 원본 | X | Y |
|---|---:|---:|
| IBM Plex Sans KR | 1.13636 | 1.13636 |
| Sarasa Mono K | 1.10 | 1.08 |

세로 위치는 Sarasa Mono K 현대 한글 전체의 중앙값을 기준선으로 삼아 원본별로
한 번만 보정합니다. 글자마다 세로 위치를 바꾸지 않으므로 한글 문장의 기준선이
흔들리지 않습니다.

## Windows에서 다시 빌드하기

필요 환경:

- Windows x64
- PowerShell 5.1 이상
- Python 3.10 이상
- 인터넷 연결(고정 버전 Python 패키지 설치 시에만 필요)

저장소 루트에서 실행합니다. 프로젝트는 `BBMonoFont` 하위 디렉터리에
있지만 `build.ps1`이 자신의 위치를 기준으로 동작하므로 별도로 이동할 필요가 없습니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\BBMonoFont\build.ps1
```

빌드 스크립트는 다음 작업을 자동으로 수행합니다.

1. `BBMonoFont/SOURCES.sha256`으로 원본 폰트와 OFL 파일을 검증합니다.
2. `.venv` 가상환경을 생성합니다.
3. 고정 버전의 FontTools와 ttfautohint를 설치합니다.
4. 네 폰트를 원본부터 다시 생성하고 자동 힌팅합니다.
5. 이름, 폭, 한글 11,172자, 힌팅 및 라이선스 메타데이터를 검증합니다.
6. `BBMonoFont/fonts/SHA256SUMS.txt`를 갱신합니다.

가상환경을 완전히 다시 만들려면 다음과 같이 실행합니다.

```powershell
.\BBMonoFont\build.ps1 -RecreateVenv
```

이미 정확한 의존성이 설치되어 있다면 `-SkipInstall`을 사용할 수 있습니다.

## 다른 운영체제에서 빌드하기

`ttfautohint-py`가 지원되는 환경에서는 다음 명령으로 동일하게 생성할 수 있습니다.

```bash
cd BBMonoFont
python -m venv .venv
. .venv/bin/activate
python scripts/verify_sources.py
python -m pip install -r requirements.txt
python scripts/build_fonts.py
python scripts/verify_fonts.py fonts
```

## 저장소 구조

```text
.
├─ .github/workflows/     GitHub Actions 빌드 검증
├─ LICENSE                빌드 코드의 MIT 라이선스
├─ README.md              GitHub 저장소 안내
└─ BBMonoFont/            프로젝트 및 폰트 빌드 본체
   ├─ fonts/              생성된 BB Mono 폰트와 검증 결과
   ├─ scripts/
   │  ├─ build_fonts.py   독립 폰트 생성기
   │  ├─ verify_fonts.py  결과 폰트 검증기
   │  └─ verify_sources.py 원본 SHA-256 검증기
   ├─ source-fonts/       수정하지 않은 원본 폰트와 OFL 원문
   ├─ build.ps1           Windows 빌드 진입점
   ├─ FONTLOG.txt         변경 이력과 설계 기록
   ├─ FONT-LICENSES.md    폰트 라이선스 안내
   ├─ SOURCES.sha256      원본 파일 고정 해시
   └─ requirements.txt    빌드 의존성 고정 버전
```

## 라이선스

- `BBMonoFont/scripts/`와 `BBMonoFont/build.ps1`: [MIT License](LICENSE)
- 원본 폰트와 생성된 BB Mono 폰트: SIL Open Font License 1.1

`Plex`와 `Source`는 각 원본의 Reserved Font Name입니다. 생성된 폰트는 이를
사용자 표시 이름에 포함하지 않고 `BB Mono I`, `BB Mono S`라는 별도 이름을
사용합니다. 자세한 저작권과 재배포 조건은
[FONT-LICENSES.md](BBMonoFont/FONT-LICENSES.md),
[빌드 도구 고지](BBMonoFont/THIRD_PARTY_NOTICES.md) 및 각 원본의 `OFL.txt`를
확인하십시오.

## English summary

BB Mono Font combines IBM Plex Mono Latin glyphs with Korean/CJK glyphs while
keeping an exact 600:1200 Latin-to-Hangul advance ratio. `BB Mono I` uses IBM
Plex Sans KR for modern Hangul, and `BB Mono S` uses Sarasa Mono K. Build code
is MIT-licensed; source and generated fonts remain under SIL OFL 1.1.
