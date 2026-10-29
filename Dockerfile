FROM node:24-bookworm-slim AS nodebuild
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY scripts/browser-sdk.js scripts/browser-sdk.js
RUN node node_modules/esbuild/bin/esbuild --bundle scripts/browser-sdk.js --format=esm --outfile=vendor/supabase.js
RUN npm prune --omit=dev --ignore-scripts

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends fonts-nanum ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=nodebuild /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY requirements-cloud.txt ./
RUN pip install --no-cache-dir -r requirements-cloud.txt
COPY --from=nodebuild /build/node_modules ./node_modules
COPY --from=nodebuild /build/vendor ./static/vendor
COPY inklab ./inklab
COPY scripts/math.cjs ./scripts/math.cjs
COPY static ./static
RUN useradd -m -u 10001 inklab && chown -R inklab:inklab /app
USER inklab
ENV PYTHONUNBUFFERED=1 INKLAB_CLOUD=1 INKLAB_DATA_DIR=/tmp/inklab INKLAB_FONT=/usr/share/fonts/truetype/nanum/NanumGothic.ttf
EXPOSE 10000
CMD ["sh","-c","exec uvicorn inklab.cloud_app:create_cloud_app --factory --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --proxy-headers --no-access-log"]
