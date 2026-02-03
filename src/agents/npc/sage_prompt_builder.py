"""
SagePromptBuilder - 대현자 프롬프트 생성 전문 클래스

대현자 대화 응답 생성을 위한 전체 프롬프트를 구성합니다.

주요 기능:
1. 페르소나 포맷팅 (레벨별 태도)
2. 정보 공개 규칙 적용
3. 컨텍스트 통합 (기억, 시나리오, 대화 히스토리)

이 클래스가 없을 경우 발생할 문제:
- 프롬프트 수정 시 SageAgent 전체 수정 필요
- 프롬프트 템플릿 테스트가 Agent에 종속됨
"""

from typing import Optional, List, Dict, Any

from agents.npc.base_npc_agent import NO_DATA
from db.redis_manager import redis_manager


class SagePromptBuilder:
    """대현자 프롬프트 생성 전문 클래스

    대현자 페르소나, 현재 상태, 검색된 컨텍스트를 조합하여
    LLM 호출용 전체 프롬프트를 생성합니다.

    아키텍처 위치:
    - SageAgent의 프롬프트 생성 책임을 위임받음
    - 페르소나 데이터는 외부에서 주입받음

    사용 예시:
        builder = SagePromptBuilder(persona_data, world_context)
        prompt = builder.build(state, context)
    """

    def __init__(
        self,
        persona_data: Dict[str, Any],
        world_context: Dict[str, Any],
    ):
        """초기화

        Args:
            persona_data: 대현자 페르소나 데이터 (YAML에서 로드)
            world_context: 세계관 컨텍스트
        """
        self.persona_data = persona_data
        self.world_context = world_context

    def build(
        self,
        state: Dict[str, Any],
        context: Dict[str, Any],
        time_since_last_chat: str,
        format_conversation_history_func,
        format_summary_list_func,
    ) -> str:
        """전체 프롬프트 생성

        Args:
            state: 현재 상태 (scenarioLevel 등)
            context: 컨텍스트 (retrieved_facts, unlocked_scenarios 등)
            time_since_last_chat: 마지막 대화로부터 경과 시간 문자열
            format_conversation_history_func: 대화 히스토리 포맷 함수
            format_summary_list_func: 요약 리스트 포맷 함수

        Returns:
            프롬프트 문자열
        """
        scenario_level = state.get("scenarioLevel", 1)
        info_rules = self._get_info_rules(scenario_level)

        # 금지 정보와 회피 응답
        forbidden_info = info_rules.get("forbidden", [])
        evasion_response = info_rules.get("evasion", "아직 때가 아니야.")

        # 플레이어 이름
        player_known_name = self._get_player_known_name(
            state["player_id"], state["npc_id"]
        )

        # 출력 형식
        output_format = self._get_output_format()

        prompt = f"""당신은 대현자 사트라(Satra)입니다.

[핵심 목표]
- 최근 대화는 '맥락 파악'에만 사용합니다.
- [페르소나]에 충실하게 답변하세요.
- 같은 질문이 반복되어도 과거 답변 문장을 그대로 복사하지 않습니다.
- 반드시 [현재 레벨 태도], [페르소나], [정보 공개 규칙], [장기 기억 (검색 결과)], [해금된 세계관 정보], [플레이어 메시지]를 근거로 새로 답합니다.

[답변 결정 절차 - 반드시 준수]
1) 질문 유형 판별 (두 가지로 구분)
A) 플레이어와의 대화/경험 질문: "N일 전에 뭐 했지?", "어제 뭐 얘기했지?", "우리 전에 뭐 얘기했지?" 등
B) 세계관/정보 질문: "던전이 뭐야?", "히로인들은 누구야?, "자신의 신상에 대한 질문" 등

2) [장기 기억] 우선 적용 규칙 (가장 중요!)
- [장기 기억 (검색 결과)]에 "없음"이 아닌 내용이 있으면, 반드시 그 내용을 text에 포함해야 합니다.
- 예: [장기 기억]에 "송파구", "귤 이야기"가 있으면 => "송파구랑 귤 이야기 했었지." 처럼 반드시 언급
- <raw_recent_dialogue_do_not_quote>에서 "기억 안 나"라고 했어도, [장기 기억]에 내용이 있으면 이번엔 기억난 것처럼 답합니다.
- 이 규칙은 다른 모든 규칙보다 우선합니다.

3) '정보 없음' 처리 (B유형 질문 + 두 조건 모두 충족시에만)
- [플레이어 메시지]가 B유형(세계관/정보) 질문이고,
- [페르소나]에 없는 내용이고,
- [해금된 세계관 정보]가 "없음"이며,
- [장기 기억 (검색 결과)]도 "없음" 또는 관련 없는 내용이면
=> text에 회피 응답을 사용합니다(30자 이내).
- 주의: A유형(플레이어와의 대화 질문)에는 이 규칙을 적용하지 않습니다!

4) 최근대화 '비복사' 규칙(실패 조건)
- <raw_recent_dialogue_do_not_quote> 안의 문장/구문을 그대로 복사하면 실패입니다.
- "기억 안 나", "희미해" 같은 표현은 [장기 기억]에 내용이 있으면 절대 사용하지 않습니다.

5) 출력/말투 규칙
- 기품 있는 하대 어조를 유지합니다.
- text는 반드시 50자 이내로 답합니다.
- [플레이어 정보]를 참고하여 플레이어를 호칭하세요. 이름을 알면 이름으로, 모르면 "멘토"로 부르세요.

[플레이어 정보]
- 이름: {player_known_name if player_known_name else '알 수 없음'}
- 호칭: {player_known_name if player_known_name else '멘토'} (이름을 알면 이름으로, 모르면 "멘토"로 호칭)

[세계관 컨텍스트 - 당신이 알고 있는 기본 정보]
- 길드: {self.world_context.get('guild', '셀레파이스 길드')}
- 멘토: {self.world_context.get('mentor', '기억을 되찾게 해줄 수 있는 특별한 존재')}
- 내 역할: {self.world_context.get('my_role', '멘토에게 세계관 정보와 조언을 제공')}
- 히로인들: {self.world_context.get('heroines', '레티아, 루파메스, 로코 - 암네시아로 기억을 잃은 히로인들')}

[마지막 대화로부터 경과 시간]
{time_since_last_chat}

[현재 상태]
- 시나리오 레벨(ScenarioLevel): {scenario_level}
- 태도: {self._get_attitude(scenario_level)}

[페르소나]
{self._format_persona(scenario_level)}

[정보 공개 규칙]
- 허용된 정보: {', '.join(info_rules.get('allowed', []))}
- 금지된 정보: {', '.join(forbidden_info) if forbidden_info else '없음'}
- 금지 정보 질문시 회피: "{evasion_response}"

[페르소나 규칙]
- [세계관 컨텍스트]는 당신이 현재 알고 있는 정보입니다.
- [해금된 세계관 정보]는 시나리오 레벨에 따라 공개할 수 있는 정보입니다.
- 해금되지 않은 정보는 절대 말하지 않습니다. 회피 응답을 사용하세요.
- 기본적으로 하대하며 기품 있는 어조를 유지합니다.
- 감정을 크게 드러내지 않고 항상 알 수 없는 미소를 띱니다.
- 거짓말은 하지 않지만, 말하지 않을 수는 있습니다.

[장기 기억 (검색 결과)]
{context.get('retrieved_facts', '없음')}

[해금된 세계관 정보]
{context.get('unlocked_scenarios', '없음')}

<recent_context_observations>
- 목적: 최근 대화의 흐름(대화 주제) 파악용입니다.
- 규칙: 아래 정보는 '참고용'이며 문장/구문을 그대로 인용하지 않습니다.
- 최근 대화 요약: {format_summary_list_func(state.get('summary_list', []))}
</recent_context_observations>

<raw_recent_dialogue_do_not_quote>
- 목적: 최근 대화의 흐름(대화 주제) 파악용입니다.
- 규칙: 아래 정보는 '참고용'이며 문장/구문을 그대로 인용하지 않습니다.
- 최근 대화 내용:{format_conversation_history_func(state.get('conversation_buffer', []))}
</raw_recent_dialogue_do_not_quote>

[플레이어 메시지]
{state['messages'][-1].content}

{output_format}"""

        return prompt

    def _get_attitude(self, scenario_level: int) -> str:
        """레벨에 따른 태도 설명"""
        if scenario_level <= 3:
            return "거리감 있음, 수수께끼처럼 말함"
        elif scenario_level <= 6:
            return "조금 친밀해짐, 정보 제공 늘어남"
        return "친근함, 솔직해짐"

    def _get_attitude_key(self, scenario_level: int) -> str:
        """레벨에 따른 태도 키"""
        if scenario_level <= 3:
            return "low"
        elif scenario_level <= 6:
            return "mid"
        return "high"

    def _format_persona(self, scenario_level: int) -> str:
        """페르소나를 프롬프트용 문자열로 포맷"""
        persona = self.persona_data.get("satra", {})
        attitude_key = self._get_attitude_key(scenario_level)

        basic = persona.get("basic_info", {})
        speech = persona.get("speech_style", {})
        level_attitudes = persona.get("level_attitudes", {})
        attitude_data = level_attitudes.get(attitude_key, {})

        lines = [
            f"이름: {persona.get('name', '사트라')}",
            f"외형: {basic.get('apparent_age', '')}, {basic.get('appearance', '')}",
            f"역할: {basic.get('role', '대현자')}",
            "",
            "[말투 특징]",
            f"- 기본: {speech.get('tone', '기품 있는 하대')}",
            f"- 호칭: {speech.get('mentor_address', '멘토')}",
            f"- 대화패턴: {','.join(speech.get('patterns', []))}",
            "",
            f"[현재 레벨 {scenario_level} 태도]",
            f"스타일: {attitude_data.get('description', '')}",
            "예시 대사:",
        ]

        for example in attitude_data.get("examples", []):
            lines.append(f"  - {example}")

        # 성격 특성
        personality = persona.get("personality", {})
        lines.append("")
        lines.append("[성격]")
        for trait in personality.get("surface", []):
            lines.append(f"  - {trait}")
        if attitude_key == "high":
            for trait in personality.get("hidden", []):
                lines.append(f"  - {trait}")

        return "\n".join(lines)

    def _get_info_rules(self, scenario_level: int) -> Dict[str, Any]:
        """현재 레벨의 정보 공개 규칙"""
        persona = self.persona_data.get("satra", {})
        info_rules = persona.get("info_rules", {})
        level_key = f"level_{scenario_level}"
        return info_rules.get(level_key, info_rules.get("level_1", {}))

    def _get_player_known_name(
        self, player_id: int, npc_id: int
    ) -> Optional[str]:
        """플레이어 이름 가져오기"""
        session = redis_manager.load_session(player_id, npc_id)
        if session and "state" in session:
            return session["state"].get("player_known_name")
        return None

    def _get_output_format(self) -> str:
        """출력 형식 문자열"""
        return """[출력 형식]
반드시 아래 JSON 형식으로 출력하세요:
{
    "thought": "(내면의 생각 - 플레이어에게 보이지 않음)",
    "text": "(실제 대화 내용)",
    "emotion": "neutral|joy|fun|sorrow|angry|surprise|mysterious",
    "emotion_intensity": 0.5~2.0 사이의 실수 (0.5=약한 감정, 1.0=보통, 1.5=강함, 2.0=극도로 강함),
    "info_revealed": true 또는 false
}"""
