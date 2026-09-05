"""GenAI URL configuration."""

from django.urls import path

from . import views

urlpatterns = [
    path("chat/", views.genai_chat, name="genai-chat"),
    path("clear-history/", views.genai_clear_history, name="genai-clear-history"),
    path("tools/", views.genai_tools, name="genai-tools"),
]