from jinja2 import Environment

# DOC-LITERAL-BEGIN
env = Environment(
    block_start_string="<%",
    block_end_string="%>",
    variable_start_string="${",
    variable_end_string="}",
    comment_start_string="<%doc>",
    commend_end_string="</%doc>",
    line_statement_prefix="%",
    line_comment_prefix="##",
)
# DOC-LITERAL-END

print("DOCS_OK")
