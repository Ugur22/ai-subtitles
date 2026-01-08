"""
Video and utility Pydantic models
"""
from pydantic import BaseModel, Field


class CleanupScreenshotsResponse(BaseModel):
    """Response from cleanup screenshots operation"""
    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Success message")
    files_deleted: int = Field(0, description="Number of files deleted")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "message": "Successfully deleted 15 screenshot files",
                "files_deleted": 15
            }
        }
    }


class UpdateFilePathResponse(BaseModel):
    """Response from updating file path"""
    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Success message")
    file_path: str = Field(..., description="Updated file path")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "message": "File path updated successfully",
                "file_path": "/static/videos/abc123.mp4"
            }
        }
    }


class DeleteTranscriptionResponse(BaseModel):
    """Response from delete transcription operation"""
    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Success message")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "message": "Transcription deleted successfully"
            }
        }
    }
