# ── Stage 1: Python build (cached independently) ─────────────────────
# Isolated so that changes to COMFYUI_REF, scripts/, etc. never
# trigger a ~20-minute Python recompilation.
FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04 AS python-builder

ARG PYTHON_VERSION=3.11.15

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN --mount=type=cache,id=apt-python-builder,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=aptlists-python-builder,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    libbz2-dev \
    libffi-dev \
    libgdbm-dev \
    liblzma-dev \
    libncursesw5-dev \
    libnss3-dev \
    libreadline-dev \
    libsqlite3-dev \
    libssl-dev \
    tk-dev \
    xz-utils \
    zlib1g-dev

RUN curl -fsSLO "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tar.xz" && \
    tar -xf "Python-${PYTHON_VERSION}.tar.xz" && \
    cd "Python-${PYTHON_VERSION}" && \
    ./configure \
      --prefix=/opt/python/${PYTHON_VERSION} \
      --enable-optimizations \
      --with-lto \
      --with-ensurepip=install && \
    make -j"$(nproc)" && \
    make install && \
    cd / && \
    rm -rf "Python-${PYTHON_VERSION}" "Python-${PYTHON_VERSION}.tar.xz" && \
    ln -s /opt/python/${PYTHON_VERSION} /opt/python/current

# ── Stage 2: Main builder ────────────────────────────────────────────
FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    COMFY_HOME=/opt/comfy \
    COMFYUI_DIR=/opt/comfy/ComfyUI \
    COMFY_VENV=/opt/comfy/venv \
    WORKSPACE_DIR=/workspace \
    STORAGE_DIR=/workspace/storage \
    CODE_SERVER_PORT=8080 \
    COMFYUI_PORT=8188 \
    CLI_ARGS= \
    PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cu128 \
    TORCH_VERSION=2.10.0 \
    TORCHVISION_VERSION=0.25.0 \
    TORCHAUDIO_VERSION=2.10.0 \
    XFORMERS_VERSION=0.0.35 \
    TRANSFORMERS_VERSION=5.12.0

ARG PYTHON_VERSION=3.11.15
ARG COMFYUI_REF=v0.24.0
ARG COMFYUI_MANAGER_REF=main
ARG CODE_SERVER_VERSION=4.103.2
ARG XFORMERS_INSTALL_MODE=wheel
# Baked custom node profile: default | image | 3d | video.
# Every profile bakes ComfyUI-Manager + custom-nodes/default.txt;
# non-default profiles add custom-nodes/<profile>.txt on top.
ARG CUSTOM_NODE_PROFILE=default
ARG BUILD_WHEEL_CACHE=1
ARG ENABLE_AGGRESSIVE_OPTIMIZATIONS=0
ARG TRITON_VERSION=3.6.0
ARG SAGEATTENTION_VERSION=0.1.0

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN --mount=type=cache,id=apt-builder,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=aptlists-builder,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    ffmpeg \
    git \
    jq \
    libbz2-dev \
    libffi-dev \
    libgdbm-dev \
    libgl1 \
    libglib2.0-0 \
    liblzma-dev \
    libncursesw5-dev \
    libnss3-dev \
    libreadline-dev \
    libsm6 \
    libsqlite3-dev \
    libssl-dev \
    libxext6 \
    libxrender1 \
    openssh-client \
    rsync \
    tk-dev \
    unzip \
    wget \
    xz-utils \
    zlib1g-dev

RUN curl -fsSL -o /tmp/code-server.deb \
      "https://github.com/coder/code-server/releases/download/v${CODE_SERVER_VERSION}/code-server_${CODE_SERVER_VERSION}_amd64.deb" && \
    dpkg -i /tmp/code-server.deb && \
    rm /tmp/code-server.deb

RUN mkdir -p "${COMFY_HOME}" "${WORKSPACE_DIR}" /opt/wheels /opt/bootstrap

COPY --from=python-builder /opt/python /opt/python

RUN --mount=type=cache,id=pip-builder,target=/root/.cache/pip \
    /opt/python/current/bin/python3 -m venv "${COMFY_VENV}" && \
    "${COMFY_VENV}/bin/pip" install --upgrade pip wheel setuptools

RUN git clone --depth 1 --branch "${COMFYUI_REF}" \
    https://github.com/comfyanonymous/ComfyUI.git "${COMFYUI_DIR}"

RUN --mount=type=cache,id=pip-builder,target=/root/.cache/pip \
    "${COMFY_VENV}/bin/pip" install \
    "torch==${TORCH_VERSION}" \
    "torchvision==${TORCHVISION_VERSION}" \
    "torchaudio==${TORCHAUDIO_VERSION}" \
    --index-url "${PYTORCH_INDEX_URL}" && \
    "${COMFY_VENV}/bin/pip" install \
    -r "${COMFYUI_DIR}/requirements.txt" && \
    "${COMFY_VENV}/bin/pip" install "transformers==${TRANSFORMERS_VERSION}"

RUN --mount=type=cache,id=pip-builder,target=/root/.cache/pip \
    if [[ "${XFORMERS_INSTALL_MODE}" == "wheel" ]]; then \
      "${COMFY_VENV}/bin/pip" install \
        "xformers==${XFORMERS_VERSION}" \
        --index-url "${PYTORCH_INDEX_URL}" \
        --no-deps; \
    elif [[ "${XFORMERS_INSTALL_MODE}" == "source" ]]; then \
      "${COMFY_VENV}/bin/pip" install --no-build-isolation "xformers==${XFORMERS_VERSION}" --no-deps; \
    else \
      echo "Unsupported XFORMERS_INSTALL_MODE=${XFORMERS_INSTALL_MODE}" >&2; \
      exit 1; \
    fi

RUN --mount=type=cache,id=pip-builder,target=/root/.cache/pip \
    "${COMFY_VENV}/bin/pip" install "huggingface_hub[cli]"

# Moved after heavy pip installs so script edits don't invalidate
# the Python / PyTorch / xformers layers above.
COPY scripts/ /opt/bootstrap/scripts/
COPY custom-nodes/ /opt/bootstrap/custom-nodes/

RUN "${COMFY_VENV}/bin/python" /opt/bootstrap/scripts/verify_protected_packages.py \
    capture \
    /opt/bootstrap/protected-package-manifest.json

RUN "${COMFY_VENV}/bin/python" /opt/bootstrap/scripts/verify_protected_packages.py \
    constraints \
    /opt/bootstrap/protected-package-manifest.json \
    /opt/bootstrap/protected-constraints.txt

RUN COMFYUI_MANAGER_REF="${COMFYUI_MANAGER_REF}" \
    bash /opt/bootstrap/scripts/install-custom-nodes.sh \
    "${CUSTOM_NODE_PROFILE}" \
    "${COMFYUI_DIR}" \
    /opt/bootstrap/custom-nodes

RUN --mount=type=cache,id=pip-builder,target=/root/.cache/pip \
    source "${COMFY_VENV}/bin/activate" && \
    export PIP_CONSTRAINT=/opt/bootstrap/protected-constraints.txt && \
    for node_dir in "${COMFYUI_DIR}"/custom_nodes/*; do \
      [[ -d "${node_dir}" ]] || continue; \
      if [[ -f "${node_dir}/requirements.txt" ]]; then \
        python -m pip install -r "${node_dir}/requirements.txt"; \
      fi; \
      if [[ -f "${node_dir}/install.py" ]]; then \
        (cd "${node_dir}" && COMFYUI_FOLDERS_BASE_PATH="${COMFYUI_DIR}" python install.py); \
      fi; \
      python /opt/bootstrap/scripts/verify_protected_packages.py \
        verify \
        /opt/bootstrap/protected-package-manifest.json; \
    done

RUN --mount=type=cache,id=pip-builder,target=/root/.cache/pip \
    if [[ "${ENABLE_AGGRESSIVE_OPTIMIZATIONS}" == "1" ]]; then \
      "${COMFY_VENV}/bin/pip" install \
        "triton==${TRITON_VERSION}" \
        "sageattention==${SAGEATTENTION_VERSION}" && \
      "${COMFY_VENV}/bin/python" /opt/bootstrap/scripts/verify_protected_packages.py \
        capture \
        /opt/bootstrap/protected-package-manifest.json; \
    else \
      "${COMFY_VENV}/bin/python" /opt/bootstrap/scripts/verify_protected_packages.py \
        verify \
        /opt/bootstrap/protected-package-manifest.json; \
    fi

RUN mkdir -p /opt/bootstrap/baked-custom-nodes && \
    cp -a "${COMFYUI_DIR}/custom_nodes/." /opt/bootstrap/baked-custom-nodes/

RUN --mount=type=cache,id=pip-builder,target=/root/.cache/pip \
    "${COMFY_VENV}/bin/python" /opt/bootstrap/scripts/verify_protected_packages.py \
      verify \
      /opt/bootstrap/protected-package-manifest.json && \
    "${COMFY_VENV}/bin/pip" freeze | tee /opt/bootstrap/base-requirements.lock >/dev/null && \
    if [[ "${BUILD_WHEEL_CACHE}" == "1" ]]; then \
      "${COMFY_VENV}/bin/pip" download \
      --extra-index-url "${PYTORCH_INDEX_URL}" \
      -r /opt/bootstrap/base-requirements.lock \
      --dest /opt/wheels || true; \
    fi

COPY start.sh /opt/bootstrap/start.sh

RUN chmod +x /opt/bootstrap/start.sh /opt/bootstrap/scripts/*.sh && \
    "${COMFY_VENV}/bin/python" - <<'PY'
import importlib
import os
from pathlib import Path
import sys
sys.path.insert(0, os.environ["COMFYUI_DIR"])
for module in ["torch", "xformers"]:
    importlib.import_module(module)
for module_file in ["server.py", "execution.py"]:
    path = Path(os.environ["COMFYUI_DIR"]) / module_file
    if not path.is_file():
        raise FileNotFoundError(f"Missing expected ComfyUI module file: {path}")
print("Smoke test passed.")
PY

RUN site_packages="$("${COMFY_VENV}/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" && \
    mkdir -p \
      /opt/runtime-slices/site-packages-audio \
      /opt/runtime-slices/site-packages-nvidia \
      /opt/runtime-slices/site-packages-rest \
      /opt/runtime-slices/site-packages-torch \
      /opt/runtime-slices/site-packages-triton \
      /opt/runtime-slices/site-packages-vision \
      /opt/runtime-slices/site-packages-xformers && \
    rsync -a \
      --exclude='/nvidia/' \
      --exclude='/torch/' \
      --exclude='/torch.libs/' \
      --exclude='/torchaudio/' \
      --exclude='/torchaudio.libs/' \
      --exclude='/torchvision/' \
      --exclude='/torchvision.libs/' \
      --exclude='/triton/' \
      --exclude='/xformers/' \
      "${site_packages}/" /opt/runtime-slices/site-packages-rest/ && \
    copy_site_package_group() { \
      local dst="$1"; \
      shift; \
      local name; \
      for name in "$@"; do \
        if [[ -e "${site_packages}/${name}" ]]; then \
          rsync -a "${site_packages}/${name}" "${dst}/"; \
        fi; \
      done; \
    }; \
    copy_site_package_group /opt/runtime-slices/site-packages-audio torchaudio torchaudio.libs && \
    copy_site_package_group /opt/runtime-slices/site-packages-nvidia nvidia && \
    copy_site_package_group /opt/runtime-slices/site-packages-torch torch torch.libs && \
    copy_site_package_group /opt/runtime-slices/site-packages-triton triton && \
    copy_site_package_group /opt/runtime-slices/site-packages-vision torchvision torchvision.libs && \
    copy_site_package_group /opt/runtime-slices/site-packages-xformers xformers

# ── Stage 3: Runtime core ────────────────────────────────────────────
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04 AS runtime-core

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    COMFY_HOME=/opt/comfy \
    COMFYUI_DIR=/opt/comfy/ComfyUI \
    COMFY_VENV=/opt/comfy/venv \
    WORKSPACE_DIR=/workspace \
    STORAGE_DIR=/workspace/storage \
    CODE_SERVER_PORT=8080 \
    COMFYUI_PORT=8188 \
    CLI_ARGS=

ARG PYTHON_VERSION=3.11.15
ARG PYTHON_ABI=3.11

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN --mount=type=cache,id=apt-runtime,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=aptlists-runtime,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    dumb-init \
    ffmpeg \
    git \
    libbz2-1.0 \
    libffi8 \
    libgdbm6 \
    libgl1 \
    libglib2.0-0 \
    liblzma5 \
    libncursesw6 \
    libnss3 \
    libreadline8 \
    libsm6 \
    libsqlite3-0 \
    libssl3 \
    libxext6 \
    libxrender1 \
    libuuid1 \
    rsync \
    tk \
    unzip \
    wget \
    zlib1g

COPY --from=builder /opt/comfy/ComfyUI /opt/comfy/ComfyUI
COPY --from=builder /opt/comfy/venv/bin /opt/comfy/venv/bin
COPY --from=builder /opt/comfy/venv/include /opt/comfy/venv/include
COPY --from=builder /opt/comfy/venv/lib64 /opt/comfy/venv/lib64
COPY --from=builder /opt/comfy/venv/pyvenv.cfg /opt/comfy/venv/pyvenv.cfg
COPY --from=builder /opt/runtime-slices/site-packages-nvidia/ /opt/comfy/venv/lib/python${PYTHON_ABI}/site-packages/
COPY --from=builder /opt/runtime-slices/site-packages-torch/ /opt/comfy/venv/lib/python${PYTHON_ABI}/site-packages/
COPY --from=builder /opt/runtime-slices/site-packages-triton/ /opt/comfy/venv/lib/python${PYTHON_ABI}/site-packages/
COPY --from=builder /opt/runtime-slices/site-packages-xformers/ /opt/comfy/venv/lib/python${PYTHON_ABI}/site-packages/
COPY --from=builder /opt/runtime-slices/site-packages-vision/ /opt/comfy/venv/lib/python${PYTHON_ABI}/site-packages/
COPY --from=builder /opt/runtime-slices/site-packages-audio/ /opt/comfy/venv/lib/python${PYTHON_ABI}/site-packages/
COPY --from=builder /opt/runtime-slices/site-packages-rest/ /opt/comfy/venv/lib/python${PYTHON_ABI}/site-packages/
COPY --from=builder /opt/bootstrap /opt/bootstrap
COPY --from=builder /opt/python /opt/python

RUN "${COMFY_VENV}/bin/python" - <<'PY'
import importlib
import os
from pathlib import Path
import sys
sys.path.insert(0, os.environ["COMFYUI_DIR"])
for module in ["torch", "xformers"]:
    importlib.import_module(module)
for module_file in ["server.py", "execution.py"]:
    path = Path(os.environ["COMFYUI_DIR"]) / module_file
    if not path.is_file():
        raise FileNotFoundError(f"Missing expected ComfyUI module file: {path}")
if (Path(os.environ["COMFYUI_DIR"]) / "custom_nodes" / "ComfyUI-Impact-Pack").is_dir():
    importlib.import_module("skimage")
print("Runtime smoke test passed.")
PY

EXPOSE 8188

ENTRYPOINT ["/usr/bin/dumb-init", "--"]

FROM runtime-core AS stable

RUN --mount=type=cache,id=apt-runtime-stable,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=aptlists-runtime-stable,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
      jq \
      openssh-client && \
    wget -q -O /usr/local/bin/runpodctl \
      "https://github.com/runpod/runpodctl/releases/latest/download/runpodctl-linux-amd64" && \
    chmod +x /usr/local/bin/runpodctl

COPY --from=builder /usr/bin/code-server /usr/bin/code-server
COPY --from=builder /usr/lib/code-server /usr/lib/code-server
COPY --from=builder /opt/wheels /opt/wheels

EXPOSE 8080

CMD ["/opt/bootstrap/start.sh"]
