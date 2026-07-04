FROM python:3.12-slim

# Install uv package manager
RUN pip install uv

# Set the working directory
WORKDIR /app

# Copy the application code
COPY . .

# Sync dependencies using uv
RUN uv sync

# Expose port 7860, which is required by Hugging Face Spaces
EXPOSE 7860

# Force bypass the ADK dev environment confirmation prompt
ENV FORCE_ALLOW=1

# Start the ADK web server bound to 0.0.0.0 on port 7860
CMD ["uv", "run", "adk", "web", "app", "--host", "0.0.0.0", "--port", "7860", "--no-reload"]
