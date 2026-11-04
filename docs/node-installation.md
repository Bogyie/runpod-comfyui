# 추가 노드의 소스 분석

`comfyctl node plan`은 후보 설치에 사용할 소스 정보를 만든다. 현재는 분석 단계까지 구현했으며, 새 노드의 의존성 해석·후보 환경 생성·설치·실행 전환은 아직 구현 중이다. 기본 노드의 enable/disable과 전환은 [세대 관리](generations.md)를 따른다.

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
