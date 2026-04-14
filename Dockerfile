FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04

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
    CLI_ARGS= \
    PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cu128 \
    TORCH_VERSION=2.7.1 \
    TORCHVISION_VERSION=0.22.1 \
    TORCHAUDIO_VERSION=2.7.1 \
    XFORMERS_VERSION=0.0.35

ARG PYTHON_VERSION=3.11
ARG COMFYUI_REF=master
ARG COMFYUI_MANAGER_REF=main
ARG IMPACT_PACK_REF=main
ARG CODE_SERVER_VERSION=4.103.2
ARG XFORMERS_INSTALL_MODE=wheel

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    dumb-init \
    ffmpeg \
    git \
    jq \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    openssh-client \
    python${PYTHON_VERSION} \
    python${PYTHON_VERSION}-dev \
    python${PYTHON_VERSION}-venv \
    rsync \
    tini \
    unzip \
    wget \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://code-server.dev/install.sh | sh -s -- --version "${CODE_SERVER_VERSION}"

RUN mkdir -p "${COMFY_HOME}" "${WORKSPACE_DIR}" /opt/wheels /opt/bootstrap

RUN python${PYTHON_VERSION} -m venv "${COMFY_VENV}" && \
    "${COMFY_VENV}/bin/pip" install --upgrade pip wheel setuptools

RUN git clone https://github.com/comfyanonymous/ComfyUI.git "${COMFYUI_DIR}" && \
    cd "${COMFYUI_DIR}" && \
    git checkout "${COMFYUI_REF}"

RUN "${COMFY_VENV}/bin/pip" install \
    "torch==${TORCH_VERSION}" \
    "torchvision==${TORCHVISION_VERSION}" \
    "torchaudio==${TORCHAUDIO_VERSION}" \
    --index-url "${PYTORCH_INDEX_URL}" && \
    "${COMFY_VENV}/bin/pip" install \
    -r "${COMFYUI_DIR}/requirements.txt"

RUN if [[ "${XFORMERS_INSTALL_MODE}" == "wheel" ]]; then \
      "${COMFY_VENV}/bin/pip" install "xformers==${XFORMERS_VERSION}" --no-deps; \
    elif [[ "${XFORMERS_INSTALL_MODE}" == "source" ]]; then \
      "${COMFY_VENV}/bin/pip" install --no-build-isolation "xformers==${XFORMERS_VERSION}" --no-deps; \
    else \
      echo "Unsupported XFORMERS_INSTALL_MODE=${XFORMERS_INSTALL_MODE}" >&2; \
      exit 1; \
    fi

RUN mkdir -p "${COMFYUI_DIR}/custom_nodes" && \
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git "${COMFYUI_DIR}/custom_nodes/ComfyUI-Manager" && \
    cd "${COMFYUI_DIR}/custom_nodes/ComfyUI-Manager" && \
    git checkout "${COMFYUI_MANAGER_REF}" && \
    git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git "${COMFYUI_DIR}/custom_nodes/ComfyUI-Impact-Pack" && \
    cd "${COMFYUI_DIR}/custom_nodes/ComfyUI-Impact-Pack" && \
    git checkout "${IMPACT_PACK_REF}"

RUN "${COMFY_VENV}/bin/pip" install \
    -r "${COMFYUI_DIR}/custom_nodes/ComfyUI-Manager/requirements.txt" && \
    "${COMFY_VENV}/bin/pip" install \
    -r "${COMFYUI_DIR}/custom_nodes/ComfyUI-Impact-Pack/requirements.txt"

RUN mkdir -p /opt/bootstrap/baked-custom-nodes && \
    cp -a "${COMFYUI_DIR}/custom_nodes/." /opt/bootstrap/baked-custom-nodes/

RUN "${COMFY_VENV}/bin/pip" freeze | tee /opt/bootstrap/base-requirements.lock >/dev/null && \
    "${COMFY_VENV}/bin/pip" download \
    -r /opt/bootstrap/base-requirements.lock \
    --dest /opt/wheels || true

COPY start.sh /opt/bootstrap/start.sh
COPY scripts/ /opt/bootstrap/scripts/

RUN chmod +x /opt/bootstrap/start.sh /opt/bootstrap/scripts/*.sh && \
    "${COMFY_VENV}/bin/python" - <<'PY'
import importlib
for module in ["torch", "xformers", "server", "execution"]:
    importlib.import_module(module)
print("Smoke test passed.")
PY

EXPOSE 8080 8188

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["/opt/bootstrap/start.sh"]
