# pxt-generate

## Usage

```powershell
py pxt-generate.py .\my-game --name "My Game" --description "Arcade prototype"
py pxt-generate.py .\my-game --dependencies "[microsoft/arcade-text, microsoft/arcade-tile-util]"
```

You can also pass dependencies from a file:

```powershell
py pxt-generate.py .\my-game --dependency-file .\deps.txt
```

## Notes

- Dependencies are resolved to the latest release tag when available, otherwise the latest tag, otherwise the default branch.
- Each dependency must be a valid MakeCode Arcade extension.
