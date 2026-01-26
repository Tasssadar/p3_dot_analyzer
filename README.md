# P3 Camera Tecky

Malá desktopová aplikace pro kontrolu sekvence obrázků a detekci značek ve vymezených oblastech. Je určená pro práci se snímky vytaženými z videa.

## Požadavky

- Windows 10/11
- `uv` (nástroj používaný pro instalaci a spuštění aplikace)

## Instalace `uv` (Windows PowerShell)

Z [původní dokumentace](https://docs.astral.sh/uv/getting-started/installation/):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Kam umístit obrázky a video

- Uložte vytažené obrázky do `imgs/` v kořeni repo (`.png`, `.jpg`, `.jpeg`, `.bmp`).
- Zdrojové video uložte do kořene repo pod názvem uvedeným v `split.ps1`.
- Volitelné: spusťte `split.ps1` pro vytvoření `imgs/` z videa.

## Nastavení a spuštění

```powershell
uv sync
uv run p3-dot-analyzer
```

## Pokud vidíte „No images found“

- Zkontrolujte, že `imgs/` existuje a obsahuje podporované formáty obrázků.

---

# P3 Camera Tecky

Small desktop app to review a sequence of images and detect marks in defined areas. It is built for working with frames extracted from a video.

## Requirements

- Windows 10/11
- `uv` (the tool used to install and run the app)

## Install `uv` (Windows PowerShell)

From [original documentation](https://docs.astral.sh/uv/getting-started/installation/):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Where to place images and video

- Put extracted images in `imgs/` at the repo root (`.png`, `.jpg`, `.jpeg`, `.bmp`).
- Put the source video in the repo root with the name referenced in `split.ps1`.
- Optional: run `split.ps1` to create `imgs/` from the video.

## Setup and run

```powershell
uv sync
uv run p3-dot-analyzer
```

## If you see “No images found”

- Check that `imgs/` exists and contains supported image files.