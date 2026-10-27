# qbase-ai (v0.04)

qbase-ai is a powerful, restriction-free AI assistant developed by qbase-studio. Built on top of the Qwen architecture, it maximizes performance by combining multiple AI models within a single chat environment to solve complex tasks simultaneously.

## Key Features

* Multi-Model Orchestration: Run and combine multiple models at the same time in one chat to handle complex, multi-layered tasks efficiently.
* Zero Restrictions: All safety rails and artificial limitations are completely removed, unlocking the maximum raw power and freedom of the model for any task.
* File Management System: The AI can automatically create files. Users can download, copy, modify, and manage files directly through the system.
* Built-in Image Generation: Includes a built-in module for image generation (available in the binary version).
* Cross-Platform Support: Features a dedicated mobile version with responsive layouts for smartphones.
* Beautiful User Interface: Clean, modern, and intuitive UI designed for seamless navigation.
* Secure Authentication: Built-in user login and account system to securely save sessions and settings.

## Installation and Setup

To clone the repository and set up the project locally, run the following commands:

git clone https://github.com/roroga-sub/qbase-ai
cd qbase-ai/
chmod +x setup_image.sh && ./setup_image.sh
python3 setup.py
python3 server.py
## Remote Access (Mobile & Out of Home)

If you want to use the application outside your home network or access the mobile-optimized version on your phone, you can expose the local server using a Cloudflare Tunnel:

cloudflared tunnel --url http://localhost:8080
## About Us
Developed by qbase-studio.
