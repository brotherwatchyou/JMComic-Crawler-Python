from typing import List, Optional


class SearchService:
    def __init__(self, option):
        self.option = option

    def search(self, query: str, page: int = 1, order_by: str = 'mr',
               category: str = '', sub_category: str = '') -> dict:
        client = self.option.new_jm_client()
        if category:
            page_obj = client.categories_filter(
                page=page,
                category=category,
                sub_category=sub_category,
                order_by=order_by,
            )
        else:
            page_obj = client.search(
                search_query=query,
                page=page,
                main_tag=0,
                order_by=order_by,
                time='a',
                category='',
                sub_category=None
            )

        results = []
        for aid, ainfo in page_obj.content:
            results.append({
                'album_id': aid,
                'title': ainfo.get('name', ''),
                'author': ainfo.get('author', ''),
                'tags': ainfo.get('tags', []),
                'category': ainfo.get('category', {}).get('title', ''),
                'sub_category': ainfo.get('category_sub', {}).get('title', ''),
                'liked': ainfo.get('liked', False),
                'is_favorite': ainfo.get('is_favorite', False),
            })

        return {
            'results': results,
            'total': page_obj.total,
            'page': page,
        }

    def search_categories(self) -> dict:
        from jmcomic import JmMagicConstants
        return {
            'categories': JmMagicConstants.CATEGORY_MAP if hasattr(JmMagicConstants, 'CATEGORY_MAP') else {},
        }
