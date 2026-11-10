# Playwright on Linux FAQ

This guide captures a working installation flow for shared Linux machines.

## When to use this guide

Use this flow when:

- `pip install -r requirements.txt` succeeds
- `python -m playwright install chromium` succeeds or only prints host validation warnings
- browser launch fails with missing runtime libraries such as `libatk*`, `libxrandr*`, or `libgbm.so.1`

The missing pieces are usually Linux shared libraries.

## Fix

```bash
pip install -r requirements.txt

conda config --env --set channel_priority strict
conda install -y -c conda-forge --override-channels \
  atk at-spi2-atk at-spi2-core libcups \
  xorg-libxcomposite xorg-libxdamage xorg-libxfixes xorg-libxrandr \
  libxkbcommon pango cairo alsa-lib mesalib mesa-libgbm-conda-x86_64

python -m playwright install chromium 

GBM_DIR=$(dirname "$(find "$CONDA_PREFIX" -name 'libgbm.so*' | head -n1)")
export LD_LIBRARY_PATH="$GBM_DIR:$CONDA_PREFIX/lib:${LD_LIBRARY_PATH:-}"
```

After that, test the runtime:

```bash
python play.py --game 01_2048
```
