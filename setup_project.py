{
 "cells": [
  {
   "cell_type": "code",
   "execution_count": 1,
   "id": "4d031a16-70a8-45e3-8a08-da7f57e29b5b",
   "metadata": {},
   "outputs": [
    {
     "name": "stdout",
     "output_type": "stream",
     "text": [
      "Project structure created successfully.\n"
     ]
    }
   ],
   "source": [
    "from pathlib import Path\n",
    "\n",
    "# Create folders\n",
    "folders = [\n",
    "    \"data/raw/daily\",\n",
    "    \"data/raw/weekly\",\n",
    "    \"data/processed\",\n",
    "    \"notebooks\",\n",
    "    \"src\",\n",
    "    \"database\",\n",
    "    \"vector_store\"\n",
    "]\n",
    "\n",
    "for folder in folders:\n",
    "    Path(folder).mkdir(parents=True, exist_ok=True)\n",
    "\n",
    "\n",
    "# Create empty files\n",
    "files = [\n",
    "    \"app.py\",\n",
    "    \"requirements.txt\",\n",
    "    \".env\",\n",
    "    \".gitignore\",\n",
    "    \"README.md\"\n",
    "]\n",
    "\n",
    "for file in files:\n",
    "    Path(file).touch(exist_ok=True)\n",
    "\n",
    "print(\"Project structure created successfully.\")"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "id": "3323b1e5-0a18-4971-9029-bd728d4d0c7a",
   "metadata": {},
   "outputs": [],
   "source": []
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python 3 (ipykernel)",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 3
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython3",
   "version": "3.13.9"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 5
}
