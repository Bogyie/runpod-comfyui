# 추가 노드의 소스 분석

`comfyctl node plan`은 후보 설치에 사용할 소스 정보를 만든다. 분석 명령과 아래 내부 환경 빌더를 구현했으며, 새 노드의 의존성 해석·코드/환경 후보 조립·설치·실행 전환을 잇는 `node add`는 아직 구현 중이다. 기본 노드의 enable/disable과 전환은 [세대 관리](generations.md)를 따른다.

```bash
comfyctl node plan PozzettiAndrea/ComfyUI-SAM3 \
  --commit de0ff5d2c2ea435d29f800abfa568cffdfb94773 > sam3-plan.json
```

저장소는 `owner/repository` 또는 정확한 HTTPS GitHub 저장소 URL, 버전은 전체 40자리 소문자 commit SHA를 받는다. 이동하는 branch/tag를 설치 버전으로 사용하지 않는다. 공개 GitHub codeload에서 archive를 받아 SHA256과 모든 일반 파일의 hash를 기록한다. 이전에 검토한 archive를 다시 검사할 때는 `--archive-sha256`을 함께 지정한다.

네트워크 없이 같은 입력을 분석할 수도 있다. 로컬 archive에는 hash가 필수다.

```bash
comfyctl node plan owner/repository --commit COMMIT_SHA \
  --archive node.tar.gz --archive-sha256 ARCHIVE_SHA256 > node-plan.json
```

명령은 일반 서비스 UID로 실행할 수 있다. 소스를 디스크에 풀거나 import하지 않고, 설치·startup·build hook도 실행하지 않는다. 현재 코드·패키지·desired 선택을 바꾸지 않으며 JSON을 표준 출력에 쓴다. 압축 크기, 전체 tar 크기, 파일별/전체 파일 크기, 항목 수, 분석용 텍스트 크기를 제한한다. 경로 탈출·symlink·hardlink·특수 파일·중복 경로·복수 최상위 디렉터리는 거부한다.

결과에는 다음이 들어간다.

- 저장소·commit·archive SHA256·전체 파일 hash와 재현 가능한 `plan_sha256`.
- requirements와 pyproject의 명시된 의존성, GPU 패키지 요구, 별도 검토가 필요한 직접 URL·include·pip 옵션.
- 설치/startup/build hook과 shell script 경로, 분석할 수 없었던 텍스트·Python·TOML 목록.
- comfy-env 설정과 AST에서 찾은 `register_nodes` 호출 위치. 두 가지가 있으면 native 후보로 표시하고, 없으면 어댑터 검토 대상으로 표시한다.

`native-comfy-env-candidate`는 실행 격리 성공 판정이 아니다. 이 분석으로 임의 Python의 동작이나 동적 의존성을 증명할 수 없다. `installation_ready`는 항상 false다. 실제 installer는 GPU lock·Python ABI·hook 정책·최종 prefix·전체 의존성 lock을 검증하고, upstream 격리 → 어댑터 → 일부 격리 → 검토한 host 예외 순서로 후보를 구성해야 한다. 분석 보고서만으로 host에 pip를 실행하지 않는다.

[실제 Linux CLI 검사](../tests/evidence/node-source-linux-cli.json)는 읽기 전용 rootfs·네트워크 차단 상태의 새 이미지에서 고정 SAM3 archive를 분석했다. [전체 분석 결과](../tests/evidence/node-source-sam3-plan.json)는 53개 파일과 native 등록 위치, 설치/startup hook 및 CUDA 검토 항목을 기록한다. 단위 검사에는 실행 시 예외를 내는 소스/hook, link·경로 탈출·중복·크기 제한, hash 불일치, 불완전한 Python/TOML 및 root가 아닌 CLI 호출이 포함된다.

## 후보 환경 빌더

내부 API `comfyctl.candidate_env.prepare_environment`는 root가 예약한 세대 아래 최종 prefix에 새 venv를 만든다. 아직 직접 사용자 명령으로 노출하지 않는다. `node add`의 source 분석·의존성 해석·노드 검증과 연결하기 위한 구성 요소다.

- 입력은 전체 exact-version/SHA256 wheel lock과 그 hash다. requirements include·직접 URL·임의 index·marker·소스 빌드는 받지 않는다. marker는 앞선 해석 단계에서 대상 플랫폼에 맞게 정규화해야 한다.
- 이미지의 GPU 패키지 목록·버전과 comfy-env SDK 버전이 다르면 prefix 생성 전에 거부한다. Python은 이미지의 `/usr/local/bin/python`을 사용한다. ABI/GPU 교체는 이미지 재빌드 범위다.
- 실제 venv 생성·wheel 설치·dependency check는 서비스 UID 1000과 다른 UID 1001, 보조 그룹 없음, `no_new_privs` 상태에서 수행한다. source/node hook을 실행하는 경로는 없다. 임의 노드 코드의 보안 sandbox를 제공한다는 뜻은 아니다.
- GPU payload만 이미지의 immutable 파일에 연결한다. GPU dist-info와 CPU 패키지는 후보 안에 따로 설치한다. host site-packages를 sys.path에 넣지 않으며 venv를 옮기거나 별칭으로 실행하지 않는다.
- wheel hash·전체 설치 버전·dependency check·GPU payload 경로를 확인하고 고정 SDK 패치를 적용한다. 성공 후 root 소유로 봉인하고 설치 캐시를 제거한다. 실패한 prefix도 봉인해 보존하며 같은 경로에 재설치하지 않는다. 기본 디스크 여유 검사와 설치 timeout을 적용한다.
- receipt의 `selected`는 false다. 노드 등록·API·GPU 실행 검증을 대신하지 않으며, 기존 세대 선택기는 아직 이런 새 환경을 활성화하지 않는다. 코드·노드 정의·lock·환경 receipt를 함께 검증하는 추가 세대 schema와 조립 단계가 필요하다.

[실제 Linux 빌더 검사](../tests/evidence/candidate-environment-cpu.json)는 새 최종 prefix에 host의 151개 패키지 lock을 실제 wheel로 설치했다. 서비스 UID로 private NumPy와 공유 torch 경로를 확인하고 후보 파일 쓰기 거부를 검사했다. GPU 버전 불일치의 생성 전 거부, 잘못된 artifact hash의 설치 실패·봉인, 실패 prefix 재사용 거부, 선택 기록·사용자 sentinel·이미지 패키지 fingerprint 보존 및 private 사용자 파일에 대한 installer 쓰기 거부를 확인했다. 성공한 설치 캐시는 제거했고 검사 컨테이너·볼륨도 삭제했다. 이 검사는 새 노드 등록이나 GPU 모델 성공을 증명하지 않는다.
