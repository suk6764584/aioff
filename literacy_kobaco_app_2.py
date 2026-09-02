import literacy_kobaco_app_1 as previous

# v1 화면 렌더러가 literacy_media_app_10에서 v9 렌더 함수를 직접 찾았지만,
# 실제 함수는 literacy_media_app_10.previous(=literacy_media_app_9)에 있습니다.
# 기존 KOBACO DB/사례 로직은 그대로 두고 렌더 함수 경로만 호환 처리합니다.
if not hasattr(previous.previous, "_render_index_v9"):
    previous.previous._render_index_v9 = previous.previous.previous._render_index_v9

app = previous.app
