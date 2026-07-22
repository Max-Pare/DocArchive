export interface User {
  id: number;
  email: string;
  is_admin: boolean;
  created_at: string;
}

export interface VisitType {
  id: number;
  key: string;
  label: string;
}

export interface Tag {
  id: number;
  name: string;
}

export interface Document {
  id: number;
  original_filename: string;
  mime_type: string;
  file_size: number;
  doc_date: string | null;
  visit_type: VisitType | null;
  title: string | null;
  notes: string | null;
  status: string;
  tags: Tag[];
  created_at: string;
  updated_at: string;
}

export interface OcrSuggestion {
  doc_date: string | null;
  visit_type_id: number | null;
  visit_type_key: string | null;
  suggested_tags: string[];
  ocr_text_excerpt: string | null;
  status: string;
}

export interface DocumentFilters {
  q?: string;
  visit_type_id?: number;
  date_from?: string;
  date_to?: string;
  tag_ids?: number[];
}
