FROM python:3.12.14-slim-bookworm
WORKDIR /app
ENV PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --create-home faro && mkdir /out && chown faro:faro /out
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY --chown=faro:faro . .
RUN pip install --no-deps --no-build-isolation -e .
USER faro
ENTRYPOINT ["faro-reconcile"]
CMD ["--help"]
