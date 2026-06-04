# Digital Earth Hackathon

Small openEO quickstart for the `digital-earth` conda environment.

## API key

There is no single global openEO API key. The Copernicus Data Space openEO backend allows basic discovery without authentication, but running processing workflows requires a registered account and OpenID Connect (OIDC) login.

The notebook keeps authentication optional:

```python
connection.authenticate_oidc()
```

That starts an interactive login flow and stores refresh tokens in the normal openEO client token store. Do not commit tokens or credentials.

## Run the notebook

```bash
conda activate digital-earth
jupyter lab notebooks/openeo_quickstart.ipynb
```

The `digital-earth` environment already has `openeo` and JupyterLab installed on this machine.

## What is included

- `notebooks/openeo_quickstart.ipynb`: Connects to the Copernicus openEO backend, lists collections, inspects Sentinel-2 metadata, and builds an NDVI process graph.
- `openeo_demo.py`: Reusable helper functions used by the notebook.
- `tests/test_openeo_demo.py`: Offline unit tests for the helpers.

## Verify

```bash
conda run -n digital-earth python -m unittest tests.test_openeo_demo
```
