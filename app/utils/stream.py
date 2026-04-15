from typing import Generator

def break_loops(stream_gen: Generator[str, None, None]) -> Generator[str, None, None]:
    """
    Monitors the stream for Repetition Collapse (a common LLM glitch where it
    repeats the same phrase recursively) and gracefully terminates the stream early.
    """
    history = ""
    for chunk in stream_gen:
        history += chunk
        yield chunk
        
        # If the last 40 characters have repeated at least 4 times recently,
        # it is caught in a repetition collapse. Sever the connection.
        if len(history) > 150:
            tail = history[-40:]
            if len(tail.strip()) > 20 and history[-400:].count(tail) >= 4:
                break


def strip_thought_blocks(stream_gen: Generator[str, None, None]) -> Generator[str, None, None]:
    """
    Wraps a token generator and drops any tokens emitted inside
    <think>...</think> or <|channel>thought...</channel|> tags, 
    so the AI's internal reasoning is hidden from the UI and history.
    """
    in_thought = False
    buffer = ""
    
    start_tags = ["<|channel>thought", "<think>", "<start_of_turn>thought"]
    end_tags = ["<channel|>", "</think>", "<|channel|>"]
    
    for chunk in stream_gen:
        buffer += chunk
        
        while buffer:
            if in_thought:
                found_end = False
                for et in end_tags:
                    idx = buffer.find(et)
                    if idx != -1:
                        # Found the end of the thought block!
                        buffer = buffer[idx + len(et):]
                        in_thought = False
                        found_end = True
                        break
                
                if found_end:
                    continue
                
                # Check for partial end tag
                idx = buffer.rfind("<")
                if idx != -1:
                    buffer = buffer[idx:]
                else:
                    buffer = ""
                break
                
            else:
                found_start = False
                first_start_idx = len(buffer)
                matched_st = ""
                
                for st in start_tags:
                    idx = buffer.find(st)
                    if idx != -1 and idx < first_start_idx:
                        first_start_idx = idx
                        matched_st = st
                        found_start = True
                        
                if found_start:
                    if first_start_idx > 0:
                        yield buffer[:first_start_idx]
                    buffer = buffer[first_start_idx + len(matched_st):]
                    in_thought = True
                    continue
                
                idx = buffer.rfind("<")
                if idx != -1:
                    if idx > 0:
                        yield buffer[:idx]
                    buffer = buffer[idx:]
                    
                    is_prefix = False
                    for st in start_tags:
                        if st.startswith(buffer):
                            is_prefix = True
                            break
                    
                    if not is_prefix:
                        yield buffer[0]
                        buffer = buffer[1:]
                        continue
                else:
                    yield buffer
                    buffer = ""
                break
                
    if not in_thought and buffer:
        yield buffer


def strip_thoughts_from_text(text: str) -> str:
    """
    Strips the thinking blocks cleanly out of a completed string.
    """
    start_tags = ["<|channel>thought", "<think>", "<start_of_turn>thought"]
    end_tags = ["<channel|>", "</think>", "<|channel|>"]
    
    while True:
        first_idx = -1
        matched_start = ""
        for st in start_tags:
            idx = text.find(st)
            if idx != -1 and (first_idx == -1 or idx < first_idx):
                first_idx = idx
                matched_start = st
        
        if first_idx == -1:
            break
            
        end_idx = -1
        search_from = first_idx + len(matched_start)
        for et in end_tags:
            idx = text.find(et, search_from)
            if idx != -1 and (end_idx == -1 or idx < end_idx):
                end_idx = idx + len(et)
                
        if end_idx != -1:
            text = text[:first_idx] + text[end_idx:]
        else:
            # unclosed thought block, strip everything after
            text = text[:first_idx]
            break
            
    return text.strip()
