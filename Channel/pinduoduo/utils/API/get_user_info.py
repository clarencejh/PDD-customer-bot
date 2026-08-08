from ..base_request import BaseRequest


class GetUserInfo(BaseRequest):
    def __init__(self, cookies=None):

        super().__init__()
        if cookies:
            self.update_cookies(cookies)
    def get_user_info(self):
        url = "https://mms.pinduoduo.com/janus/api/new/userinfo"
        result_data = self.get_user_details()
        if result_data is not False:
            return (
                result_data.get('id'),
                result_data.get('username'),
                result_data.get('mall_id'),
            )
        return False

    def get_user_details(self):
        """Return the platform user payload, including ``mallOwner``."""
        url = "https://mms.pinduoduo.com/janus/api/new/userinfo"
        result = self.post(url, data="")
        if result and result.get("success") is True:
            return result.get('result', {})
        else:
            error_msg = result.get('errorMsg') if result else "获取用户信息失败"
            self.logger.error(f"获取用户信息失败: {error_msg}")
            return False
