ARG ROS_BASE_IMAGE=bj-warehouse.tencentcloudcr.com/phanthy-motus/ros-base:latest
FROM ${ROS_BASE_IMAGE}
WORKDIR /work/meeting-assistant
COPY meeting_assistant/ /work/meeting-assistant/meeting_assistant/
COPY assets/ /work/meeting-assistant/assets/
ENV PYTHONUNBUFFERED=1 ROS_DOMAIN_ID=42 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
ENV FASTRTPS_DEFAULT_PROFILES_FILE=/opt/phanthy-motus/dds-local.xml
ENV MEETING_DB=/opt/phanthy-motus/data/meeting-assistant/meetings.sqlite3
EXPOSE 15740
CMD ["python3", "-m", "meeting_assistant.server"]
