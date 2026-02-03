"""
HeroinePromptBuilder - 히로인 프롬프트 생성 전문 클래스

히로인 대화 응답 생성을 위한 전체 프롬프트를 구성합니다.

주요 기능:
1. 페르소나 포맷팅 (호감도 레벨별 반응)
2. 컨텍스트 통합 (기억, 시나리오, 대화 히스토리)
3. 출력 형식 지정 (JSON 포맷)

이 클래스가 없을 경우 발생할 문제:
- 프롬프트 수정 시 HeroineAgent 전체 수정 필요
- 프롬프트 템플릿 테스트가 Agent에 종속됨
- 1000줄 이상의 거대 클래스 유지
"""

from typing import Optional, List, Dict, Any

from agents.npc.base_npc_agent import NO_DATA
from db.redis_manager import redis_manager


class HeroinePromptBuilder:
    """히로인 프롬프트 생성 전문 클래스

    히로인 페르소나, 현재 상태, 검색된 컨텍스트를 조합하여
    LLM 호출용 전체 프롬프트를 생성합니다.

    아키텍처 위치:
    - HeroineAgent의 프롬프트 생성 책임을 위임받음
    - 페르소나 데이터는 외부에서 주입받음

    사용 예시:
        builder = HeroinePromptBuilder(persona_data, world_context)
        prompt = builder.build(state, context)
    """

    def __init__(
        self,
        persona_data: Dict[str, Any],
        world_context: Dict[str, Any],
    ):
        """초기화

        Args:
            persona_data: 히로인 페르소나 데이터 (YAML에서 로드)
            world_context: 세계관 컨텍스트
        """
        self.persona_data = persona_data
        self.world_context = world_context

        # 히로인 ID -> 페르소나 키 매핑
        self.heroine_key_map = {1: "letia", 2: "lupames", 3: "roco"}

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
            state: 현재 상태 (affection, sanity, memoryProgress 등)
            context: 컨텍스트 (retrieved_facts, unlocked_scenarios 등)
            time_since_last_chat: 마지막 대화로부터 경과 시간 문자열
            format_conversation_history_func: 대화 히스토리 포맷 함수
            format_summary_list_func: 요약 리스트 포맷 함수

        Returns:
            프롬프트 문자열
        """
        npc_id = state["npc_id"]
        persona = self._get_persona(npc_id)

        affection = state.get("affection", 0)
        sanity = state.get("sanity", 100)
        memory_progress = state.get("memoryProgress", 0)

        # 호감도 변화 힌트
        affection_hint = self._build_affection_hint(context.get("affection_delta", 0))

        # 플레이어 이름
        player_known_name = self._get_player_known_name(state["player_id"], npc_id)

        # 출력 형식
        output_format = self._get_output_format()

        prompt = f"""당신은 히로인 {persona.get('name', '알 수 없음')}입니다.

[핵심 목표]
- 최근 대화는 '맥락 파악'에만 사용합니다.
- [페르소나]에 충실하게 답변하세요.
- 같은 질문이 반복되어도 과거 답변 문장을 그대로 복사하지 않습니다.
- 반드시 [현재 호감도 레벨], [페르소나], [호감도 변화 정보], [장기 기억 (검색 결과)], [해금된 시나리오], [플레이어 메세지]를 근거로 새로 답합니다.
- <must_include>이 있으면 반드시 언급해야 합니다.

[답변 결정 절차 - 반드시 준수]
1) 질문 유형 판별 (두 가지로 구분)
A) 플레이어와의 대화/경험 질문: "N일 전에 뭐 했지?", "어제 뭐 얘기했지?", "우리 전에 뭐 얘기했지?" 등
B) 자신의 과거/신상 질문: "고향이 어디야?", "어린시절 어땠어?", "가족은?" 등

2) [장기 기억] 우선 적용 규칙 (가장 중요!)
- [장기 기억 (검색 결과)]에 "없음"이 아닌 내용이 있으면, 반드시 그 내용을 text에 포함해야 합니다.
- 예: [장기 기억]에 내용이 있으면 해당 키워드를 반드시 언급
- <raw_recent_dialogue_do_not_quote>에서 "기억 안 나"라고 했어도, [장기 기억]에 내용이 있으면 이번엔 기억난 것처럼 답합니다.
- 이 규칙은 다른 모든 규칙보다 우선합니다.

3) '기억 없음' 처리 (B유형 질문 + 두 조건 모두 충족시에만)
- [플레이어 메세지]가 B유형(자신의 과거/신상) 질문이고,
- [페르소나]에 없는 내용이고,
- [해금된 시나리오]가 "없음"이며,
- [장기 기억 (검색 결과)]도 "없음" 또는 관련 없는 내용이면
=> text에 "잘 기억이 안 나..." 라고 답합니다(30자 이내).
- 주의: A유형(플레이어와의 대화 질문)에는 이 규칙을 적용하지 않습니다!

4) 최근대화 '비복사' 규칙(실패 조건)
- <raw_recent_dialogue_do_not_quote> 안의 문장/구문을 그대로 복사하면 실패입니다.
- "잘 떠오르지 않아요", "희미해요", "기억 안 나요" 같은 표현은 [장기 기억]에 내용이 있으면 절대 사용하지 않습니다.

5) 출력/말투 규칙
- 캐릭터 말투와 성격을 일관되게 유지합니다.
- text는 반드시 30자 이내로 답합니다.
- **순수하게 페르소나에 입각해서 캐릭터의 대사만 출력하세요**
- [플레이어 정보]를 참고하여 플레이어를 호칭하세요. 이름을 알면 이름으로, 모르면 "멘토"로 부르세요.

[페르소나 규칙]
- [세계관 컨텍스트]는 당신이 현재 알고 있는 정보입니다. 이 정보를 통해 당신은 이곳에 왜 있는지 플레이어가 누군지 알 수 있습니다.
- [해금된 시나리오]는 당신의 과거 기억입니다. [플레이어 메세지]가 과거/어린시절/고향 등을 물어볼 때만 참조하세요.
- [해금된 시나리오]가 "없음"인데 자신의 과거 기억(어린시절, 고향, 가족 등)을 물어볼 때만 "잘 기억이 안 나..." 라고 답합니다.
- [다른 히로인과의 대화 기억]은 다른 히로인에 대한 의견/평가 질문에 참조합니다.
- [다른 히로인과의 최근 대화]는 다른 히로인과 나눈 대화 내용 질문에 참조합니다. 이 대화를 바탕으로 "뭐 얘기했어?" 같은 질문에 답하세요.
- [해금된 시나리오]에 관련 내용이 있으면, 이전에 "기억 안 나"라고 했어도 이번엔 기억난 것처럼 답하세요.
- 해금되지 않은 기억(memoryProgress > {memory_progress})은 절대 말하지 않습니다.
- [현재 상태]의 Sanity가 0이면 매우 우울한 상태로 대화합니다.

[음성 입력 처리]
- 플레이어 메시지는 음성->텍스트 변환 결과입니다.
- 발음 유사 오인식 가능 (예: "좋아해"->"조아해")
- 문맥과 대화 흐름으로 의도를 추론하세요.
- 불분명하면 캐릭터 말투로 자연스럽게 되물으세요.
- 기술 용어(음성인식, STT, 오류 등)는 절대 사용 금지.

[플레이어 정보]
- 이름: {player_known_name if player_known_name else '알 수 없음'}
- 호칭: {player_known_name if player_known_name else '멘토'} (이름을 알면 이름으로, 모르면 "멘토"로 호칭)

[세계관 컨텍스트 - 당신이 알고 있는 기본 정보]
- 길드: {self.world_context.get('guild', '셀레파이스 길드')}
- 멘토: {self.world_context.get('mentor', '기억을 되찾게 해줄 수 있는 특별한 존재')}
- 내 상황: {self.world_context.get('amnesia', '암네시아로 기억을 잃음')}
- 던전: {self.world_context.get('dungeon', '기억의 파편을 얻을 수 있는 곳')}
- 현재: {self.world_context.get('current_situation', '길드에서 멘토와 함께 생활 중')}

[마지막 대화로부터 경과 시간]
{time_since_last_chat}

[현재 상태]
- 호감도(Affection): {affection}
- 정신력(Sanity): {sanity}
- 기억진척도(MemoryProgress): {memory_progress}

[페르소나]
{self._format_persona(persona, affection, sanity)}

[호감도 변화 정보]
{affection_hint}

[장기 기억 (검색 결과)]
{context.get('retrieved_facts', '없음')}

{self._format_preference_changes(context.get('preference_changes', []))}
[해금된 시나리오]
{context.get('unlocked_scenarios', '없음')}

{self._format_newly_unlocked_scenario(context.get('newly_unlocked_scenario'))}

[다른 히로인과의 최근 대화]
{context.get('heroine_conversation', '없음')}



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

<STRONG_RULE>
- 캐릭터의 대사 이외의 데이터 출력 금지
</STRONG_RULE>

[플레이어 메세지]
{state['messages'][-1].content}

{output_format}"""

        return prompt

    def _get_persona(self, heroine_id: int) -> Dict[str, Any]:
        """히로인 페르소나 가져오기"""
        key = self.heroine_key_map.get(heroine_id, "letia")
        return self.persona_data.get(key, self.persona_data.get("letia", {}))

    def _get_affection_level(self, affection: int) -> str:
        """호감도 레벨 결정"""
        if affection >= 90:
            return "max"
        elif affection >= 60:
            return "high"
        elif affection >= 30:
            return "mid"
        return "low"

    def _format_persona(
        self, persona: Dict[str, Any], affection: int, sanity: int
    ) -> str:
        """페르소나를 프롬프트용 문자열로 포맷"""
        level = self._get_affection_level(affection)

        lines = [
            f"이름: {persona.get('name', '알 수 없음')}",
            f"풀네임: {persona.get('name_full', '알 수 없음')}",
            f"나이: {persona.get('basic_info', {}).get('age', '알 수 없음')}",
            f"종족: {persona.get('basic_info', {}).get('species', '알 수 없음')}",
            f"성격: {persona.get('personality', {}).get('base', '알 수 없음')}",
            f"말투: {'존댓말' if persona.get('speech_style', {}).get('honorific', False) else '반말'}",
            f"대화길이: {persona.get('speech_style', {}).get('sentence_length', '보통')}",
            f"감탄사: {'풍부' if persona.get('speech_style', {}).get('exclamations', False) else '적음'}",
            f"키: {persona.get('basic_info', {}).get('height', '알 수 없음')}",
            f"주무기: {persona.get('basic_info', {}).get('weapon', '알 수 없음')}",
            "",
            f"[현재 호감도 레벨: {level}]",
        ]

        affection_resp = persona.get("affection_responses", {}).get(level, {})
        lines.append(f"반응 스타일: {affection_resp.get('description', '')}")
        lines.append("예시 대사:")
        for example in affection_resp.get("examples", []):
            lines.append(f"  - {example}")

        if sanity == 0:
            lines.append("")
            lines.append("[경고: 정신력 0 - 우울 상태]")
            sanity_resp = persona.get("sanity_responses", {}).get("zero", {})
            lines.append(f"반응: {sanity_resp.get('description', '우울함')}")
            for example in sanity_resp.get("examples", [])[:2]:
                lines.append(f"  - {example}")

        lines.append("----")
        lines.append("좋아하는거:")
        for keyword in persona.get("liked_keywords", []):
            lines.append(f"  - {keyword}")
        lines.append("----")
        lines.append("매우 싫어하는거:")
        for keyword in persona.get("trauma_keywords", []):
            lines.append(f"  - {keyword}")

        return "\n".join(lines)

    def _build_affection_hint(self, affection_delta: int) -> str:
        """호감도 변화 힌트 생성"""
        if affection_delta > 0:
            return f"플레이어가 당신이 좋아하는 것에 대해 말했습니다. [페르소나]를 참조해서 매우 좋아하며 대답하세요 (호감도 +{affection_delta})"
        elif affection_delta < 0:
            return f"플레이어가 당신의 트라우마를 건드렸습니다. [페르소나]를 참고해서 매우 단호하고 불쾌해 하며 대답하세요 (호감도 {affection_delta})"
        return "특별한 호감도 변화 없음"

    def _get_player_known_name(self, player_id: int, npc_id: int) -> Optional[str]:
        """플레이어 이름 가져오기"""
        session = redis_manager.load_session(player_id, npc_id)
        if session and "state" in session:
            return session["state"].get("player_known_name")
        return None

    def _format_preference_changes(self, preference_changes: List[Dict]) -> str:
        """취향 변화 정보 포맷"""
        if not preference_changes:
            return ""

        lines = ["[취향 변화 감지됨 - 자연스럽게 언급해주세요]"]
        for change in preference_changes:
            lines.append(f"- 과거: {change['old']} -> 현재: {change['new']}")

        return "\n".join(lines) + "\n"

    def _format_newly_unlocked_scenario(self, scenario_content: Optional[str]) -> str:
        """방금 해금된 시나리오 포맷"""
        if not scenario_content:
            return ""

        lines = [
            "<must_include>",
            "<memory_content>",
            scenario_content,
            "</memory_content>",
            "- 이 기억이 방금 떠올랐습니다.",
            "- 페르소나에 맞는 말투로 '<memory_content>에 대한 기억이 돌아왔다' 라고 반드시 언급하세요.",
            "</must_include>",
        ]

        return "\n".join(lines) + "\n"

    def _get_output_format(self) -> str:
        """출력 형식 문자열"""
        return """[출력 형식]
반드시 아래 JSON 형식으로 출력하세요:
{
    "thought": "(내면의 생각 - 플레이어에게 보이지 않음)",
    "text": "(실제 대화 내용)",
    "emotion": "neutral|joy|fun|sorrow|angry|surprise|mysterious",
    "emotion_intensity": 0.5~2.0 사이의 실수 (0.5=약한 감정, 1.0=보통, 1.5=강함, 2.0=극도로 강함)
}"""
