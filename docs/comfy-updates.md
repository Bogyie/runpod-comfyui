# ComfyUI 업데이트

기본 경로는 안정 release의 SHA를 확인해 업데이트 초안을 만들고, 후보 이미지의 CPU·두 GPU 검증 후 같은 digest를 승격하는 것이다. 노드와 GPU 스택은 함께 최신화하지 않는다.

```bash
# 최신 안정 release 확인. 추적 파일은 바꾸지 않는다.
uv run --frozen python tools/rebuild/update_comfy.py
# 소스·host 입력과 lock, 변경이 필요한 worker 입력과 lock을 준비한다.
uv run --frozen python tools/rebuild/update_comfy.py --apply
# 명시적 ref도 검토 후보로 준비할 수 있다. 안정 release 판정과는 다르다.
uv run --frozen python tools/rebuild/update_comfy.py --ref FULL_COMMIT_SHA --apply
```

스크립트는 ComfyUI 한 저장소만 resolve한다. 고정한 노드·SDK 소스와 GPU lock을 유지하고, 기존 lock의 버전을 우선하면서 변경된 요구사항을 해석한다. GPU 제약과 충돌하면 준비 단계에서 실패하며 기반층을 자동 교체하지 않는다. 모든 입력과 lock을 staging에서 생성한 뒤 추적 파일에 반영한다. 동일 버전·artifact 집합에서 resolver 주석만 달라지면 기존 lock 바이트를 유지한다.

`.github/workflows/comfy-update.yml`은 수동 실행으로 같은 준비와 단위 검사를 수행한다. 변경이 있고 `create_pr`를 켜면 초안 PR을 만들고 `rebuild-image.yml`을 명시적으로 dispatch한다. 자동 stable 승격은 없다. 보고서와 patch는 artifact에 남긴다. 최신 release가 같으면 PR·이미지를 새로 만들지 않는다.

PR 생성에는 workflow에 선언한 쓰기 권한 외에 저장소의 **Allow GitHub Actions to create and approve pull requests** 설정이 필요하다. 작성 시 API 조회에서는 이 설정이 꺼져 있었다. 설정은 변경하지 않았으며 원격 자동 PR 생성은 아직 검증하지 않았다. 새 workflow의 기본 브랜치 반영·원격 수동 실행도 최종 배포 검증 범위에 남아 있다. 토큰을 이미지나 저장소에 넣는 방식으로 우회하지 않는다.

현재 [실제 준비 검사](../tests/evidence/comfy-update-preparation.json)는 v0.44.0 이후 공식 커밋 `5f415e31abfd837870bbc733ba1e158de71ed985`를 고정해 프런트엔드 1.57.6→1.58.5만 바뀌고 GPU·5개 worker lock과 노드 pin이 유지됨을 확인했다. Linux amd64 대상으로 macOS에서 의존성을 해석한 증거이며 PR·GPU·운영 이미지 승격 증거는 아니다. 현재 최신 안정 release 조회는 기존 v0.44.0과 같아 변경 없이 끝났다.

이미지를 바꿀 때 실행 계약이 같으면 기존 선택을 재사용한다. ComfyUI·의존성이 바뀌면 [명시적 rebase와 이미지 복귀](generations.md#명시적-이미지-rebase)를 사용한다. `env rollback`만으로 이전 이미지로 바뀌지는 않는다. 실제 새 ComfyUI 코드·프런트엔드·노드 계산·원본 digest 복귀 검사는 별도 통합 gate로 수행한다.
