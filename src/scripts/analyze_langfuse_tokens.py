"""
LangFuse 토큰 사용량 분석 스크립트 (v3 API 호환)

LangFuse API를 통해 traces와 observations를 가져와서 토큰 사용량을 분석합니다.

사용법:
    # 기본 분석 (최근 1일)
    uv run python src/scripts/analyze_langfuse_tokens.py
    
    # 최근 7일
    uv run python src/scripts/analyze_langfuse_tokens.py --days 7
    
    # CSV로 저장
    uv run python src/scripts/analyze_langfuse_tokens.py --export-csv
"""

import os
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Any
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

try:
    from langfuse import Langfuse
except ImportError:
    print("❌ langfuse 패키지가 설치되지 않았습니다.")
    print("   실행: uv sync")
    exit(1)


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description="LangFuse 토큰 사용량 분석")
    parser.add_argument("--days", type=int, default=1, help="최근 N일 데이터 (기본: 1)")
    parser.add_argument("--export-csv", action="store_true", help="CSV 파일로 export")
    
    args = parser.parse_args()
    
    # LangFuse 클라이언트 초기화
    print("🔧 LangFuse 클라이언트 초기화 중...\n")
    client = Langfuse()
    
    # Traces 가져오기
    from_timestamp = datetime.now() - timedelta(days=args.days)
    
    print(f"📥 LangFuse에서 traces 가져오는 중...")
    print(f"   기간: {from_timestamp.strftime('%Y-%m-%d')} ~ 현재")
    print(f"   최대: 100개\n")
    
    try:
        traces_response = client.api.trace.list(
            from_timestamp=from_timestamp,
            limit=100,
        )
        traces = traces_response.data if hasattr(traces_response, 'data') else []
        print(f"✅ {len(traces)}개 traces 가져오기 완료\n")
    except Exception as e:
        print(f"❌ Traces 가져오기 실패: {e}")
        exit(1)
    
    if not traces:
        print("⚠️ Trace가 없습니다.")
        print("   NPC API를 먼저 호출하거나 --days 값을 늘려보세요.")
        exit(0)
    
    # 통계 수집
    print("🔍 토큰 사용량 분석 중...\n")
    
    model_stats = defaultdict(lambda: {
        "count": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_tokens": 0,
    })
    
    trace_name_stats = defaultdict(lambda: {"count": 0, "total_tokens": 0})
    tag_stats = defaultdict(lambda: {"count": 0, "total_tokens": 0})
    
    total_observations = 0
    
    # 각 trace의 observations 조회
    for i, trace in enumerate(traces, 1):
        trace_id = trace.id if hasattr(trace, 'id') else trace.get("id")
        trace_name = trace.name if hasattr(trace, 'name') else trace.get("name", "unknown")
        trace_tags = trace.tags if hasattr(trace, 'tags') else trace.get("tags", [])
        
        if i <= 3:  # 처음 3개만 상세 로그
            print(f"   분석 중: {trace_name} (ID: {trace_id[:16]}...)")
        elif i == 4:
            print(f"   ... (나머지 {len(traces) - 3}개)")
        
        try:
            # Observations 조회
            obs_response = client.api.observations_v_2.get_many(
                trace_id=trace_id,
                limit=100,
                fields="core,basic,usage"
            )
            observations = obs_response.data if hasattr(obs_response, 'data') else []
            total_observations += len(observations)
            
            for obs in observations:
                # 모델 이름 추출
                if isinstance(obs, dict):
                    model = obs.get("model", obs.get("providedModelName", "unknown"))
                    usage = obs.get("usage", {})
                else:
                    model = getattr(obs, "model", None) or getattr(obs, "provided_model_name", "unknown")
                    usage = getattr(obs, "usage", {}) or {}
                
                # Usage 정보 추출
                if isinstance(usage, dict):
                    input_tokens = usage.get("input", 0) or 0
                    output_tokens = usage.get("output", 0) or 0
                    total_tokens = usage.get("total", 0) or (input_tokens + output_tokens)
                else:
                    input_tokens = getattr(usage, "input", 0) or 0
                    output_tokens = getattr(usage, "output", 0) or 0
                    total_tokens = getattr(usage, "total", 0) or (input_tokens + output_tokens)
                
                # 모델별 집계
                if model and total_tokens > 0:
                    model_stats[model]["count"] += 1
                    model_stats[model]["total_input_tokens"] += input_tokens
                    model_stats[model]["total_output_tokens"] += output_tokens
                    model_stats[model]["total_tokens"] += total_tokens
                    
                    # Trace 이름별 집계
                    trace_name_stats[trace_name]["count"] += 1
                    trace_name_stats[trace_name]["total_tokens"] += total_tokens
                    
                    # 태그별 집계
                    for tag in (trace_tags or []):
                        tag_stats[tag]["count"] += 1
                        tag_stats[tag]["total_tokens"] += total_tokens
                        
        except Exception as e:
            print(f"⚠️ Trace {trace_id[:16]}... 처리 실패: {e}")
    
    print(f"\n✅ 총 {total_observations}개 observations 분석 완료\n")
    
    # 결과 출력
    print("="*70)
    print("📊 LangFuse 토큰 사용량 분석 리포트")
    print("="*70)
    print()
    
    print(f"📌 총 Trace 수: {len(traces)}개")
    print(f"📌 총 Observation 수: {total_observations}개\n")
    
    # 모델별 통계
    print("🤖 모델별 토큰 사용량:")
    print("-"*70)
    
    if model_stats:
        for model, stats in sorted(model_stats.items(), 
                                  key=lambda x: x[1]['total_tokens'], 
                                  reverse=True):
            print(f"\n📦 모델: {model}")
            print(f"   호출 횟수: {stats['count']:,}회")
            print(f"   Input tokens: {stats['total_input_tokens']:,}")
            print(f"   Output tokens: {stats['total_output_tokens']:,}")
            print(f"   Total tokens: {stats['total_tokens']:,}")
            
            if stats['count'] > 0:
                avg = stats['total_tokens'] / stats['count']
                print(f"   평균 tokens/호출: {avg:.1f}")
    else:
        print("  ⚠️ 토큰 정보가 없습니다.")
        print("  원인: 모델이 usage를 반환하지 않거나 observations가 비어있음")
    
    print("\n" + "="*70 + "\n")
    
    # Trace 이름별 통계
    print("📝 Trace 이름별 호출 횟수:")
    print("-"*70)
    
    if trace_name_stats:
        for name, stats in sorted(trace_name_stats.items(), 
                                 key=lambda x: x[1]['count'], 
                                 reverse=True):
            print(f"   {name:40s} {stats['count']:4d}회  {stats['total_tokens']:8,} tokens")
    else:
        print("   데이터 없음")
    
    print("\n" + "="*70 + "\n")
    
    # 태그별 통계
    print("🏷️  태그별 토큰 사용량:")
    print("-"*70)
    
    if tag_stats:
        for tag, stats in sorted(tag_stats.items(), 
                                key=lambda x: x[1]['total_tokens'], 
                                reverse=True):
            print(f"   {tag:30s} {stats['count']:4d}회  {stats['total_tokens']:8,} tokens")
    else:
        print("   ⚠️ 태그 없음 (metadata 전달 확인 필요)")
    
    print("\n" + "="*70 + "\n")
    
    # CSV Export
    if args.export_csv:
        try:
            import pandas as pd
            
            rows = []
            for trace in traces:
                trace_id = trace.id if hasattr(trace, 'id') else trace.get("id")
                
                try:
                    obs_response = client.api.observations_v_2.get_many(
                        trace_id=trace_id,
                        limit=100,
                        fields="core,basic,usage"
                    )
                    observations = obs_response.data if hasattr(obs_response, 'data') else []
                    
                    for obs in observations:
                        if isinstance(obs, dict):
                            model = obs.get("model", "unknown")
                            usage = obs.get("usage", {})
                        else:
                            model = getattr(obs, "model", "unknown")
                            usage = getattr(obs, "usage", {}) or {}
                        
                        rows.append({
                            "timestamp": trace.timestamp if hasattr(trace, 'timestamp') else trace.get("timestamp"),
                            "trace_id": trace_id,
                            "trace_name": trace.name if hasattr(trace, 'name') else trace.get("name"),
                            "model": model,
                            "input_tokens": usage.get("input", 0) if isinstance(usage, dict) else getattr(usage, "input", 0),
                            "output_tokens": usage.get("output", 0) if isinstance(usage, dict) else getattr(usage, "output", 0),
                            "total_tokens": usage.get("total", 0) if isinstance(usage, dict) else getattr(usage, "total", 0),
                        })
                except:
                    pass
            
            if rows:
                df = pd.DataFrame(rows)
                filename = f"langfuse_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                df.to_csv(filename, index=False, encoding='utf-8-sig')
                print(f"💾 CSV 저장 완료: {filename}")
                print(f"   Excel에서 열어서 분석 가능!\n")
            else:
                print("⚠️ CSV 저장 실패: 데이터 없음\n")
                
        except ImportError:
            print("⚠️ pandas 설치 필요: uv sync\n")
    
    print("✅ 분석 완료!")
    print("\n💡 Tip: 더 상세한 정보는 LangFuse 대시보드에서 확인하세요:")
    print("   https://us.cloud.langfuse.com")


if __name__ == "__main__":
    main()
