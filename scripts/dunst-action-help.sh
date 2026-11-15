#!/usr/bin/env bash
# Documentation only: print setup instructions; never modify desktop settings.
set -eu

cat <<'EOF'
i3.ai-deck 알림 액션 설정 안내

이 스크립트는 안내만 출력합니다. 설치·설정 변경·알림 전송을 하지 않습니다.
앱의 알림 액션 연결은 아직 미구현이며, 아래 설정만으로 이동되지는 않습니다.

별도 적용 스크립트 (실제 설정 변경에는 사용자 허가가 필요):
  python3 scripts/configure-dunst-action.py          # 차이만 미리보기
  python3 scripts/configure-dunst-action.py --apply  # 백업·설정 수정·dunst 재로드

필요한 도구
  - 실행 중인 dunst 알림 데몬
  - --action 옵션을 지원하는 notify-send (Ubuntu 패키지: libnotify-bin)
  - 설정 적용에 사용할 dunstctl (dunst 패키지에 포함)

설정 파일: ~/.config/dunst/dunstrc
  기존 [global] 섹션의 mouse_left_click을 다음 값으로 설정합니다.
  [global] 섹션이나 같은 옵션을 중복해서 추가하지 않습니다.
  사용자 설정 파일이 없다면 기존 시스템 설정을 바탕으로 준비합니다.

  [global]
  mouse_left_click = do_action, close_current

직접 설정을 변경한 뒤 적용:
  dunstctl reload

역할 분담
  dunst: 왼쪽 클릭 -> 알림이 제공한 기본 액션 실행 -> 알림 닫기
  ai-deck: notify-send에 --action=default=이동을 추가
           -> 액션 결과(default)와 원본 세션 ID를 연결
           -> 기존 model.py / i3.py로 현재 쌍 전환 + 대상 터미널 포커스

설정에는 에이전트 제목이나 CLI 이동 명령을 넣지 않습니다.
왼쪽 클릭 설정은 다른 앱의 알림에도 적용됩니다.
기본 가운데 클릭은 이미 액션 실행이므로 설정 변경 없이 사용할 수도 있습니다.
i3 설정 파일은 변경할 필요가 없습니다.

참고: https://dunst-project.org/documentation/faq/
EOF
