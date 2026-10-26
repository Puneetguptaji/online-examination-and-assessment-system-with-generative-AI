-- ExamAI Python Edition — MySQL 8 schema
-- Safe to run more than once: creates missing objects and never drops the database.
CREATE DATABASE IF NOT EXISTS examai_python
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE examai_python;

CREATE TABLE IF NOT EXISTS users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    full_name     VARCHAR(100) NOT NULL,
    email         VARCHAR(150) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          ENUM('STUDENT','TEACHER') NOT NULL DEFAULT 'STUDENT',
    roll_no       VARCHAR(30) NULL,
    course        VARCHAR(80) NOT NULL DEFAULT 'MCA (AI & ML)',
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_users_role (role)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS exams (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    title            VARCHAR(150) NOT NULL,
    subject          VARCHAR(80) NOT NULL,
    description      TEXT NULL,
    duration_minutes INT NOT NULL DEFAULT 30,
    total_marks      INT NOT NULL DEFAULT 0,
    randomize        BOOLEAN NOT NULL DEFAULT TRUE,
    status           ENUM('DRAFT','PUBLISHED','CLOSED') NOT NULL DEFAULT 'DRAFT',
    created_by       INT NOT NULL,
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_exam_teacher FOREIGN KEY (created_by) REFERENCES users(id),
    INDEX idx_exam_status (status),
    INDEX idx_exam_owner (created_by)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS questions (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    exam_id        INT NOT NULL,
    question_text  TEXT NOT NULL,
    option_a       VARCHAR(500) NOT NULL,
    option_b       VARCHAR(500) NOT NULL,
    option_c       VARCHAR(500) NOT NULL,
    option_d       VARCHAR(500) NOT NULL,
    correct_option CHAR(1) NOT NULL,
    topic          VARCHAR(100) NOT NULL DEFAULT 'General',
    marks          INT NOT NULL DEFAULT 1,
    explanation    TEXT NULL,
    source         ENUM('MANUAL','AI') NOT NULL DEFAULT 'MANUAL',
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_question_exam FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE,
    CONSTRAINT chk_question_answer CHECK (correct_option IN ('A','B','C','D')),
    CONSTRAINT chk_question_marks CHECK (marks > 0),
    INDEX idx_question_exam (exam_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS attempts (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    exam_id        INT NOT NULL,
    student_id     INT NOT NULL,
    started_at     DATETIME NOT NULL,
    deadline_at    DATETIME NOT NULL,
    submitted_at   DATETIME NULL,
    score          INT NOT NULL DEFAULT 0,
    total_marks    INT NOT NULL DEFAULT 0,
    percentage     DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    status         ENUM('IN_PROGRESS','SUBMITTED','AUTO_SUBMITTED') NOT NULL DEFAULT 'IN_PROGRESS',
    question_order JSON NOT NULL,
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_attempt_exam_student UNIQUE (exam_id, student_id),
    CONSTRAINT fk_attempt_exam FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE,
    CONSTRAINT fk_attempt_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_attempt_student (student_id),
    INDEX idx_attempt_exam (exam_id),
    INDEX idx_attempt_status (status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS answers (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    attempt_id      INT NOT NULL,
    question_id     INT NOT NULL,
    selected_option CHAR(1) NULL,
    is_correct      BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT uq_answer_attempt_question UNIQUE (attempt_id, question_id),
    CONSTRAINT fk_answer_attempt FOREIGN KEY (attempt_id) REFERENCES attempts(id) ON DELETE CASCADE,
    CONSTRAINT fk_answer_question FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
    CONSTRAINT chk_selected_option CHECK (selected_option IS NULL OR selected_option IN ('A','B','C','D'))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS ai_drafts (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    teacher_id     INT NOT NULL,
    exam_id        INT NOT NULL,
    topic          VARCHAR(120) NOT NULL,
    difficulty     VARCHAR(20) NOT NULL,
    question_text  TEXT NOT NULL,
    option_a       VARCHAR(500) NOT NULL,
    option_b       VARCHAR(500) NOT NULL,
    option_c       VARCHAR(500) NOT NULL,
    option_d       VARCHAR(500) NOT NULL,
    correct_option CHAR(1) NOT NULL,
    explanation    TEXT NOT NULL,
    status         ENUM('PENDING','APPROVED','REJECTED') NOT NULL DEFAULT 'PENDING',
    model          VARCHAR(80) NOT NULL,
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_draft_teacher FOREIGN KEY (teacher_id) REFERENCES users(id),
    CONSTRAINT fk_draft_exam FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE,
    CONSTRAINT chk_draft_answer CHECK (correct_option IN ('A','B','C','D')),
    INDEX idx_draft_status (status, teacher_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS ai_feedback (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    attempt_id   INT NOT NULL UNIQUE,
    content      JSON NOT NULL,
    model        VARCHAR(80) NOT NULL,
    generated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_feedback_attempt FOREIGN KEY (attempt_id) REFERENCES attempts(id) ON DELETE CASCADE
) ENGINE=InnoDB;
