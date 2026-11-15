# 질문 대기 보강

## 범위

- 쌍 이름 편집은 제외한다.
- Python 표준 라이브러리와 현재 실행 중인 Codex rollout의 읽기 전용 관찰을 유지한다.
- i3·dunst·Codex 설정을 바꾸거나 실행 래퍼·새 app-server를 요구하지 않는다.
- 질문 본문·답변을 별도 저장하지 않고 호출 ID와 미응답 질문 번호만 메모리에 둔다.

## 확인한 근거

설치된 Codex는 0.169.0이다. 현재 실행 중인 8개 세션을 읽기 전용으로 조사했다.
두 로그에서 다음 순서를 확인했다. 대화 내용은 복사하지 않았다.

1. response_item/function_call의 name=request_user_input_async. arguments에 questions 배열.
2. 동일 call_id의 function_call_output은 {"accepted":true}. 이것은 접수이며 사용자 답변이 아니다.
3. response_item/message의 role=user에 send_user_message_question_reply 래퍼가 온다.
4. 내부 배열의 questionItemId는 JSON 문자열 ["request_user_input_async", call_id, 질문 번호]다.
   한 요청에 여러 질문이 있으면 답변도 질문별로 도착할 수 있다.

기존 코드는 name=request_user_input만 처리하므로 비동기 질문을 놓친다.
도구 접수 직후 질문을 지우면 미응답 질문을 놓친다. 그러나 task_complete 이후에도
질문 UI가 남는다는 초기 판단은 잘못이었다. 아래 Codex TUI 수명에 맞춰 정정한다.

## 상태 전이와 검증 기준

- 동기식 request_user_input: 호출 시 wait, 같은 호출의 결과가 오면 run.
- 비동기 질문: 실제 questions와 call_id가 있는 요청만 등록하고 wait 표시.
- accepted=true는 wait를 해제하지 않는다. 명시적인 접수 실패는 해당 요청을 제거한다.
- 턴 도중에는 답변 ID가 일치하는 질문만 제거한다. 모두 답하면 원래 활동 상태로 복귀한다.
- 턴 진행 중 여러 요청이 동시에 있거나 질문 일부만 답했으면 wait 유지.
- task_complete는 미응답 질문도 제거하고 done으로 전환한다. Codex TUI의 질문 UI 종료와 맞춘다.
- 새 task_started에서도 이전 턴의 대기를 제거한다. 답변 기록을 만들어내지는 않는다.
- 턴 중단은 대기를 해제한다. 종료 세션은 기존처럼 목록에서 숨긴다.
- 다른 호출의 결과·다른 요청의 답변·손상된 답변은 대기를 임의로 해제하지 않는다.
- 포커스나 n/N 선택으로 질문을 해소하지 않는다. n은 wait 행을 확인 대상으로 삼는다.
- 기존 완료 알림 정책은 유지한다. 질문 전용 알림은 이번 범위에 추가하지 않는다.
- 과거에 답한 질문이 서버 재시작 후 wait로 부활하지 않도록 전체 로그 재생도 검증한다.

## 일반 승인 대기와 한계

현재 조사한 실행 중인 rollout의 이벤트 종류에는 승인 대기를 나타내는 항목이 없었다.
이는 모든 Codex 버전·로그에 없다는 뜻은 아니다.

공식 app-server 문서에는 명령 실행·파일 변경 승인 요청과 serverRequest/resolved,
사용자 질문 요청이 별도 실시간 프로토콜로 정의된다. 이 프로토콜의 존재가 현재
CLI의 rollout에 같은 이벤트를 기록하거나 외부 관찰자가 구독할 수 있음을 뜻하지 않는다.

- [공식 승인 요청 흐름](https://learn.chatgpt.com/docs/app-server#approvals)
- [공식 사용자 입력 요청](https://learn.chatgpt.com/docs/app-server#toolrequestuserinput)

현재 로그에서 일반 승인 요청을 확인하기 전에는 명령 내용·긴 실행 시간·창 제목으로
추측하지 않는다. 비동기 질문 지원을 먼저 구현하고 추가 연동이 필요하면 별도 논의한다.

## 최초 구현 결과와 검수 중 발견한 문제

- deck/observe.py에서 활동 상태와 미응답 질문을 분리하고, 미응답 질문이 있으면
  waiting을 우선 표시한다. 기존 TUI의 wait와 n 대상 선택을 그대로 사용한다.
- 동기·비동기 질문 결과, 복수 요청·일부 답변, 접수 실패·턴 중단, 무관하거나
  손상된 답변, 전체 로그 재생 후 이미 답한 질문의 대기 부활 방지를 검증했다.
- 실제 실행 중인 두 세션의 비동기 질문 로그를 재생해 대기 진입과 답변 후 해제를 확인했다.
  질문·답변 본문은 출력하거나 별도 보존하지 않았다. 전체 테스트 54개 통과.
- 일반 승인 대기 감지와 질문 전용 데스크톱 알림은 추가하지 않았다.

검수: 선택형 질문을 띄운 상태에서 wait 표시와 n 선택을 확인한다. 포커스를 바꿔도
wait가 유지되어야 하며, 답변하면 run 또는 done으로 돌아와야 한다.

## Codex TUI 질문 수명과 수정

사용자 검수에서 질문에 답하지 않았는데 Shift+Left로도 질문이 열리지 않고 ai-deck만
wait로 남는 문제가 나왔다. 기존 테스트는 질문이 턴을 넘어 살아남는다는 잘못된 가정을 검증했다.

Codex 0.169.0 소스를 확인했다.

- chatwidget/protocol.rs의 live TurnStatus::Completed 분기는 take_question_drafts를 호출한다.
- bottom_pane/async_questions/state.rs의 take_pending_drafts는 clear_pending을 호출한다.
- 따라서 최종 응답으로 턴이 종료되면 미응답이어도 CLI의 원래 질문 선택 UI는 사라진다.
  일반 대화에서 답하지 않았다는 사실과 지금 답할 수 있는 UI가 존재하는지는 다르다.
- ai-deck이 이 시점에도 wait를 유지한 것은 ai-deck의 버그다. 단축키 문제로 오인하면 안 된다.

근거:
- [0.169.0 완료 시 질문 정리](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/tui/src/chatwidget/protocol.rs#L491)
- [0.169.0 질문 draft 회수와 clear_pending](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/tui/src/bottom_pane/async_questions/state.rs#L207)

수정: 턴 종료·새 턴 시작 시 이전 질문 대기를 해제한다. 사용자가 답변했다고 표시하거나
답변 이벤트를 만들지 않는다. 질문을 새로 만들거나 Codex 설정을 수정하지 않는다.
종료 전 부분 답변·동시 질문 추적은 유지한다. 종료 후 늦은 답변이나 서버 재시작으로
이전 대기가 다시 살아나지 않는 회귀 테스트를 추가한다.

검수: 기존 세션이 wait에 고정되지 않는지 확인한다. 새로운 질문은 턴 진행 중에만
검수하며, 최종 응답 이후 이미 닫힌 질문을 선택하라고 안내하지 않는다.
